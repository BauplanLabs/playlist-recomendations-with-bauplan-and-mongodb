# Playlist recomendations with Bauplan and MongoDB

This repository is a reference implementation demonstrating how to use [bauplan](https://www.bauplanlabs.com/) and [MongoDB](https://www.mongodb.com/) to build a full-stack recommender system.

This application is an embedding-based recommender system from music playlists, using bauplan for data preparation and model training and [MongoDB Atlas](https://www.mongodb.com/products/platform/atlas-database) for serving.

We use the _Spotify Million Playlist Dataset_ (originally from [AI Crowd](https://www.aicrowd.com/)) - available as sample dataset in the [bauplan sandbox](https://www.bauplanlabs.com/#join).

## Overview

Given sequences of music tracks - Spotify playlists -, we wish to learn an embedding for each track, and use these embeddings to recommend similar tracks using vector similarity at inference time. 

In particular, we showcase how to train a sequential model on playlists. The application can be easily changed to use a transformer model on metadata.

We then use a [Streamlit](https://streamlit.io/) app as an intuitive UI for users to explore the embedding space and get music recommendations based on the tracks they like: you can imagine the live endpoint as answering a question like "given that the user is listening to this track, what track do you recommend to play next?". 

_Credits_: The data wrangling code is adapted from the [NYU Machine Learning System Course](https://github.com/jacopotagliabue/MLSys-NYU-2022) by [Jacopo Tagliabue](https://jacopotagliabue.it/) and [Ethan Rosenthal](https://www.ethanrosenthal.com/).

### Data flow

In the full-stack application, the data flows as follows between tools and environments:

1. The original dataset is stored in AWS S3, as a bauplan-backed [Iceberg](https://iceberg.apache.org/) table. The dataset is already available in the bauplan sandbox in the `public` namespace - note that this dataset is available as "One Big Table".
2. The end-to-end data pipeline is in `src/bpln_pipeline` and comprises the data preparation and training steps as simple decorated Python functions - running the pipeline with bauplan will execute these functions and persist the embeddings both in an Iceberg table and in MongoDB Atlas.
3. The Streamlit app in `src/app` showcases how to retrieve the embeddings from bauplan (higher latency / high throughput) and from MongoDB (lower latency / low throughput) to explore the vector space and the recommendations in real-time.

Note: both the pipeline and the app code are heavily commented. Do not hesitate to reach out to the Bauplan team for any questions or clarifications - shoot an email to ciro.greco@bauplanlabs.com.

![bpln_mongo_pipeline](https://github.com/user-attachments/assets/ae59c15b-3ad0-4605-953d-13ffda1249a1)

## Setup

### Python environment

To run the project, you need Python 3.10 or higher. We recommend using a virtual environment to manage dependencies:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Bauplan

* [Join](https://www.bauplanlabs.com/#join) bauplan's sandbox, sign in, create your username and API key.
* The sandbox includes several public datasets - including the one used in this project.
* Check out our 3-min [tutorial](https://docs.bauplanlabs.com/en/latest/tutorial/index.html) to get familiar with the platform.

### MongoDB Atlas

* [Sign up](https://account.mongodb.com/account/login?nds=true) for a MongoDB account and create a cluster Atlas.
* Write down your username and password, and the connection string to your cluster. To find your string in your Atlas console, click on your Cluster and then on `Connect/Drivers/`. Scroll to the section `Add your connection string into your application code` and use the connection string in there, making sure to replace the variables with your database password (for more on Connection Strings, check MongoDB's [documentation](https://www.mongodb.com/docs/manual/reference/connection-string/)).
* In `Cluster > Security > Network Access`, make sure your cluster is reachable from bauplan by enabling: `Allow access from anywhere (0.0.0.0/0)`.

## Run

### Check out the dataset

Bauplan comes with its own CLI. To get acquainted with the dataset and its schema simply run in the terminal:

```bash
bauplan table get public.spotify_playlists
```

You can also query the data by passing SQL statements to `bauplan query` in the CLI. For instance, to retrieve the top 10 artists in the dataset run:

```bash
bauplan query "SELECT artist_name, artist_uri, COUNT(*) as _C FROM public.spotify_playlists GROUP BY ALL ORDER BY _C DESC LIMIT 10"
```

### Running the pipeline with bauplan

To run the pipeline - i.e. the DAG going from the original table to the vector space -- you first will create a [data branch](https://docs.bauplanlabs.com/en/latest/tutorial/02_catalog.html) to develop safely in the cloud.

```bash
cd src/bpln_pipeline
bauplan branch create <YOUR_USER_NAME>.music_recommendations
bauplan branch checkout <YOUR_USER_NAME>.music_recommendations
```

Now, add the Mongo URI as a secret to your bauplan project allowing bauplan to connect to the cluster securely:

```bash
bauplan parameter set --name mongo_uri --value "mongodb+srv://aa:aaa@caa.bbb.mongodb.net/" --type secret
```

If you inspect your `bauplan_project.yml` file in the `pipeline` folder, you will see the new parameter as `mongo_uri`:

```yaml
parameters:
    mongo_uri:
        type: secret
        default: kUg6q4141413...
        key: awskms:///arn:aws:kms:us-...
```

You can now run the entire pipeline in the cloud by simply running:

```bash
bauplan run
```

Once the system is done, you can check that we successfully created the embedding table directly from the CLI:

```bash
bauplan table get track_vectors_with_metadata
```

You can also query the final table to get the most represented authors in the vector space:

```bash
bauplan query "SELECT artist_name, COUNT(*) as _C FROM track_vectors_with_metadata GROUP BY 1 ORDER BY 2 DESC LIMIT 10"
```

### Serving recommendations with MongoDB

We can visualize the structure of the embedding space using the Streamlit app, and then ask for recommendations leveraging the low-latency query capabilities of MongoDB. You will need to pass the Mongo URI (the same one used before to generate the secret) as an environment variable to connect to the database. You will also pass your branch name to the app.

To run the Streamlit app, run:

```bash
cd src/app
MONGO_URI=<YOUR_MONGO_URI> streamlit run explore_and_recommend.py -- --bauplan_user_name <YOUR_BAUPLAN_USERNAME>
```

Note: make sure that the vector search index created by the bauplan pipeline is completed before running the app (check the MongoDB Atlas dashboard).

The app will open in your browser, and you can start exploring the embedding space and asking for recommendations. Note how easy it is to interact with both bauplan and MongoDB from any Python process using the `bauplan` and `pymongo` libraries.

## Where to go from here?

Building embeddings from sequences is not the only way to produce track-to-track recommendations. For example, we can also use metadata to build text-based embeddings. This is a stub to get your started (also showcasing how to use transformers from the Hugging Face model hub):

```python
@bauplan.python('3.11', pip={'sentence-transformers': '3.1.1'})
# note that we are using the internet_access=True flag to allow this function
# to download the transformer model from the Hugging Face hub
@bauplan.model(internet_access=True)
def content_to_vectors(
    tracks=bauplan.Model(
      'public.spotify_playlists',
        # extract track metadata
        columns=[
            'track_name',
            'artist_name',
            'track_uri'
        ],
        filter="num_followers > $num_followers and num_tracks > $num_tracks"
    )
):
    from sentence_transformers import SentenceTransformer
    # instantiate the transformer model  
    model = SentenceTransformer("distiluse-base-multilingual-cased-v1")
    # encode the content wih the model
    embeddings = model.encode([list_of_metadata_strings_here])
    # finish the function...
```

## License

The code in this repository is released under the MIT License and provided as is.
