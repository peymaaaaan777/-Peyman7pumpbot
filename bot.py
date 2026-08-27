import requests

url = "https://api.geckoterminal.com/api/v2/networks/solana/new_pools"

r = requests.get(
    url,
    headers={"Accept": "application/json"},
    timeout=20
)

print("STATUS:", r.status_code)
print(r.text[:10000])
