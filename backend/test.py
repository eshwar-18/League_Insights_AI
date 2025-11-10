import requests

payload = {
    "gameName": "Ash",
    "tagLine": "69420"
}

resp = requests.post(
    "http://127.0.0.1:5000/generate-recap",
    json=payload
)

print("STATUS:", resp.status_code)
print("RESPONSE:")
print(resp.text)
