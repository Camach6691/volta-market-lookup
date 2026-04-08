# Volta Global — Market Lookup App

Paste a CoStar/Crexi link **or** any address to instantly get the Tier and key self-storage metrics for that market.

## Deploy in 3 steps (free, 5 minutes)

### 1. Push this folder to GitHub
Create a new repo on https://github.com/new (can be private), then:
```bash
cd volta-market-lookup
git init
git add .
git commit -m "Initial deploy"
git remote add origin https://github.com/YOUR_USERNAME/volta-market-lookup.git
git push -u origin main
```

### 2. Connect to Streamlit Cloud
- Go to https://share.streamlit.io → **New app**
- Select your GitHub repo
- Main file path: `app.py`
- Click **Deploy**

### 3. Share the link
Streamlit gives you a URL like `https://yourapp.streamlit.app` — share it with the team.

## Local dev
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Data
- `data/sub_markets.csv` — 5,175 sub-markets across 32 states, scored on 8 criteria
- Tier A = top 12% · B = next 9% · C = next 11% · D & E = lower tiers
