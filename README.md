# FitHer

FitHer is a fitness and wellness prototype with a web app and a WeChat mini program. It lets users record workouts, daily habits and menstrual cycles, and ask a Qwen-powered assistant about fitness and nutrition. The assistant uses ChromaDB to retrieve food and exercise information and can use the signed-in user's profile to tailor its replies.

A [13-response survey](data/survey_summary.md) helped prioritize cycle tracking and carrying profile details into follow-up chats.

## Run locally

From the repository root, create a Python 3.12 environment and install the dependencies.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

On Windows PowerShell, create the environment with `py -3.12 -m venv .venv` and activate with `.\.venv\Scripts\Activate.ps1`. Copy [`.env.example`](.env.example) to `.env`, set `DASHSCOPE_API_KEY`, and set `SECRET_KEY` to a unique value generated with `python -c "import secrets; print(secrets.token_hex(32))"`. The app uses a local SQLite database by default. On an existing installation, changing `SECRET_KEY` signs users out.

### Prepare the retrieval index

1. Put the USDA Foundation Foods CSV files in the directory named in [`scripts/fetch_usda.py`](scripts/fetch_usda.py). Run `python scripts/fetch_usda.py` to create `data/raw/usda/foods.json`.
2. Set `RAPIDAPI_KEY` for the exercise API used by [`scripts/fetch_exercises.py`](scripts/fetch_exercises.py). Run `python scripts/fetch_exercises.py` to create `data/raw/exercises/exercises.json`.
3. From the repository root, run `python scripts/build_vectorstore.py` to build the two ChromaDB collections used by the assistant.

### Start the app

```bash
uvicorn api.main:app --reload --port 8000
```

Open [the web app](http://127.0.0.1:8000) or [API documentation](http://127.0.0.1:8000/docs). To build the WeChat mini program, run `npm ci` and `npm run build:mp-weixin` in [`fitness-mini/`](fitness-mini/). Configure the WeChat variables in `.env` to enable WeChat login.

## Repository guide

- [`api/`](api/) contains FastAPI routes, profile and tracking models, and chat streaming.
- [`src/rag_pipeline.py`](src/rag_pipeline.py) retrieves foods and exercises and assembles the Qwen prompt.
- [`frontend/`](frontend/) contains the web app. [`fitness-mini/`](fitness-mini/) contains the Vue mini program.

Run `python -m unittest test_api` to check profile access against an in-memory database. A benchmark for retrieval and answer quality is future work.

Built by [Linxuan Li](https://github.com/LinxuanLi-DS) as an educational and portfolio project. FitHer is intended for fitness and wellness information. Medical diagnosis and treatment are outside its scope.
