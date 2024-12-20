"""

This is a script that takes the JSON files of the Spotify dataset and upload them to S3
in a bucket as flattened parquet files. Once files are in S3, they can be used to create
Iceberg tables using bauplan built-in functions and abstractions.

This code does NOT need to run as part of the reference implementation, as the dataset is already
available in bauplan's data catalog whenever a new user join the public sandbox. However, it is useful
both as a reference to the original processing and upload choices, as well as a template for users who
wish to upload their own datasets to S3 and use bauplan SDK to quickly get versionable, branchable, 
and queryable tables out of files.

To run:

python dataset_to_s3.py

Check the code for the arguments you can pass to the script.

"""

import bauplan
import boto3
import json
import concurrent.futures
import os
from datetime import datetime
import pyarrow as pa
import pyarrow.parquet as pq
import tempfile


def flatten_playlist(playlist: dict):
    # playlist level data we care about
    playlist_data = {
        'playlist_name': playlist['name'],
        'playlist_id': playlist['pid'],
        'num_followers': playlist['num_followers'],
        'modified_at': playlist['modified_at'],
        'num_tracks': playlist['num_tracks'],
        'num_albums': playlist['num_albums']
    }
    # rows are dictionaries with the playlist data and the track data merged
    return [{**playlist_data, **track} for track in playlist['tracks']]


def parse_and_upload(
    s3_client,
    s3_bucket: str,
    s3_folder: str,
    json_file: str
):
    """
    
    In a threadpool, this function will open each file, 
    parse the JSON, flatten the playlist data, and upload it to S3.
    
    """
    # read the json file
    with open(json_file, 'r') as f:
        data = json.load(f)
    # get the file name without the path and the extension
    file_name = os.path.basename(json_file).replace('.json', '')
    # get the playlist data    
    all_playlists = data['playlists']
    # add each track to the rows
    all_rows =[]
    for playlist in all_playlists:
        all_rows.extend(flatten_playlist(playlist))
    # create a temporary parquet file from the list of dictionaries
    # and upload it to S3
    with tempfile.NamedTemporaryFile() as tmp:
        table = pa.Table.from_pylist(all_rows)
        pq.write_table(table, tmp.name)
        s3_client.upload_file(tmp.name, s3_bucket, f"{s3_folder}/{file_name}.parquet")
              
    return


def add_files_to_bauplan_catalog(
    s3_bucket: str,
    s3_folder: str,
    table_name: str,
    ingestion_branch: str
):
    """
    
    We leverage the bauplan SDK to create a table from the S3 URI
    and add data to it in a pure Pythonic way.
    
    While not the focus of this, note the use of data branches to sandbox the upload
    and safely merge new tables into the production branch of the lakehouse.
    
    For a deeper dive into the Write-Audit-Publish pattern for ingestion, see our blog post:
    
    https://www.prefect.io/blog/prefect-on-the-lakehouse-write-audit-publish-pattern-with-bauplan
    
    """
    # instantiate the bauplan client
    bpln_client = bauplan.Client()
    # create ingestion branch if it does not exist
    if not bpln_client.has_branch(ingestion_branch):
        bpln_client.create_branch(ingestion_branch, from_ref='main')
    # create table from S3 URI
    s3_uri = f's3://{s3_bucket}/{s3_folder}/*.parquet'
    bpln_table = bpln_client.create_table(
        table=table_name,
        search_uri=s3_uri,
        branch=ingestion_branch,
        # we use the public namespace, and assume it's already created
        namespace='public',
        replace=True
    )
    print(f"Table {table_name} created!")
    # add the data
    plan_state = bpln_client.import_data(
        table=table_name,
        search_uri=s3_uri,
        branch=ingestion_branch,
        namespace='public',
        client_timeout=60*60
    )
    if plan_state.error:
        raise Exception(f"Error importing data: {plan_state.error}")
    # merge the branch to main
    bpln_client.merge_branch(source_ref=ingestion_branch, into_branch='main')
    
    return


def upload_and_process(
    local_file_path: str,
    s3_bucket: str,
    s3_folder: str,
    table_name: str,
    ingestion_branch: str
):
    # start the upload
    print(f"\nStarting the upload at {datetime.now()}\n")
    # instantiate the s3 client - we assume the envs / local credentials are already set and working
    # with the target bucket
    s3_client = boto3.client('s3')
    # list all json files in the local folder
    files = [os.path.join(local_file_path, f) for f in os.listdir(local_file_path) if f.endswith('.json')]
    print(f"Found {len(files)} files to upload: first one is {files[0]}")
    # run the process + upload in parallel
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
       future_to_files = {executor.submit(parse_and_upload, s3_client, s3_bucket, s3_folder, file): file for file in files}
       for future in concurrent.futures.as_completed(future_to_files):
           _f = future_to_files[future]
           try:
               data = future.result()
           except Exception as exc:
               print(f"{_f} generated an exception: {exc}")
           else:
               print(f"{_f} uploaded successfully.")
    # now that the files are in S3, we can create the Iceberg table in bauplan
    add_files_to_bauplan_catalog(
        s3_bucket=s3_bucket,
        s3_folder=s3_folder,
        table_name=table_name,
        ingestion_branch=ingestion_branch
    )
    # say goodbye
    print(f"\nUploaded done at {datetime.now()}.\n\nSee you, Space Cowboy.")
    return


if __name__ == '__main__':
    import argparse
    # parse arguments from the command line
    parser = argparse.ArgumentParser()
    parser.add_argument('--local_file_path', type=str, default='/Users/apo/Downloads/spotify_million_playlist_dataset/data')
    parser.add_argument('--s3_bucket', type=str, default='alpha-hello-bauplan')
    parser.add_argument('--s3_folder', type=str, default='spotify')
    parser.add_argument('--table_name', type=str, default='spotify_playlists')
    parser.add_argument('--ingestion-branch', type=str, default='jacopo.spotify_ingestion')
    args = parser.parse_args()
    
    upload_and_process(
        local_file_path=args.local_file_path,
        s3_bucket=args.s3_bucket,
        s3_folder=args.s3_folder,
        table_name=args.table_name,
        ingestion_branch=args.ingestion_branch
    )