import logging
import sys
import requests
from config import config
import json
import pprint
from confluent_kafka import SerializingProducer
from confluent_kafka.serialization import StringSerializer
from confluent_kafka.schema_registry.avro import AvroSerializer
from confluent_kafka.schema_registry import SchemaRegistryClient


def fetch_playlist_items_page(google_api_key, youtube_playlist_id, page_token=None):
    response = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", 
                            params={
                                "key": google_api_key,
                                "playlistId": youtube_playlist_id,
                                "part": "contentDetails",
                                "page_token": page_token
                            })
    payload = json.loads(response.text)
    logging.debug("Got %s", payload)
    return payload

def fetch_videos_page(google_api_key, video_id, page_token=None):
    response = requests.get("https://www.googleapis.com/youtube/v3/videos", 
                            params={
                                "key": google_api_key,
                                "id": video_id,
                                "part": "snippet,statistics",
                                "page_token": page_token
                            })
    payload = json.loads(response.text)
    logging.debug("Got %s", payload)
    return payload

def fetch_playlist_items(google_api_key, youtube_playlist_id, page_token=None):
    payload = fetch_playlist_items_page(google_api_key, youtube_playlist_id, page_token=None)
    
    # keep asking results from the payload list
    if "items" in payload:  # Check if 'items' key is present in the payload
        yield from payload["items"]

    # use the dictionary's get funs to get the "nextPageToekn" if there's one
    next_page_token = payload.get("nextPageToken")

    # recursion to call the func
    if next_page_token is not None:
        yield from fetch_playlist_items(google_api_key, youtube_playlist_id, page_token=None)

def fetch_videos(google_api_key, youtube_playlist_id, page_token=None):
    payload = fetch_videos_page(google_api_key, youtube_playlist_id, page_token)
    
    if "items" in payload:  # Check if 'items' key is present in the payload
        yield from payload["items"]

    next_page_token = payload.get("nextPageToken")

    if next_page_token is not None:
        yield from fetch_videos(google_api_key, youtube_playlist_id, next_page_token)

def summarize_video(video):

    return {
        "video_id": video["id"],
        "title": video["snippet"]["title"],
        "views": int(video["statistics"].get("viewCount", 0)),
        "likes": int(video["statistics"].get("likeCount", 0)),
        "comments": int(video["statistics"].get("commentCount", 0)),
    }

def on_delivery(err, record):
    pass

def main():
    logging.info("START")

    schema_registry_client = SchemaRegistryClient(config["schema_registry"])
    youtube_videos_value_schema = schema_registry_client.get_latest_version("youtube_videos-value")
    
    kafka_config = config["kafka"].copy()
    kafka_config.update({
        "key.serializer": StringSerializer(),   #StringSerializer is used for the key, assuming it's a string.

        # value.serializer is defined as a lambda function that converts the value to a JSON string and encodes it as bytes. 
        "value.serializer": AvroSerializer(     #set up the AvroSerializer, and provide the Avro schema used for serialization
            schema_registry_client,
            youtube_videos_value_schema.schema.schema_str,
        )
    })
    # Configure the producer with AvroSerializer for values
    producer = SerializingProducer(kafka_config)

    google_api_key = config["google_api_key"]
    youtube_playlist_id = config['youtube_playlist_id']
    
    for video_item in fetch_playlist_items(google_api_key, youtube_playlist_id):
        video_id = video_item["contentDetails"]["videoId"]
        for video in fetch_videos(google_api_key, video_id):
            logging.info("GOT %s", pprint.pformat(summarize_video(video)))

            # create a producer - a Kafka write-only connection. To write my data packet to a topic
            # Produce messages to the Kafka topic
            producer.produce(
                topic="youtube_videos",
                key = video_id,
                value = {
                        "my_field1": "value_for_my_field1", 
                        "TITLE": video["snippet"]["title"],
                        "VIEWS": int(video["statistics"].get("viewCount", 0)),
                        "LIKES": int(video["statistics"].get("likeCount", 0)),
                        "COMMENTS": int(video["statistics"].get("commentCount", 0)),
                },
                on_delivery = on_delivery
            )
    

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    sys.exit(main())