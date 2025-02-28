import sys
from turtle import pd
import lancedb
import pyarrow as pa

RGW_ENDPOINT=str(sys.argv[0])
BUCKET_PATH=str(sys.argv[1])
REGION=str(sys.argv[2])
ACCESS_KEY=str(sys.argv[3])
SECRET_KEY=str(sys.argv[4])

db = lancedb.connect(
    BUCKET_PATH,
    storage_options={
        "endpoint" : RGW_ENDPOINT,
        "region"   : REGION,
        "access_key_id" : ACCESS_KEY,
        "secret_access_key" : SECRET_KEY,
    }
)

data = [
    {"vector": [3.1, 4.1], "item": "foo", "price": 10.0},
    {"vector": [5.9, 26.5], "item": "bar", "price": 20.0},
]

df = pd.DataFrame(
    [
        {"vector": [3.1, 4.1], "item": "foo", "price": 10.0},
        {"vector": [5.9, 26.5], "item": "bar", "price": 20.0},
    ]
)
tbl = db.create_table("table_from_df", data=df)

schema = pa.schema([pa.field("vector", pa.list_(pa.float32(), list_size=2))])
tbl = db.create_table("empty_table", schema=schema)

print(db.table_names())