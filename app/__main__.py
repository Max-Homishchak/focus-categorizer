import logging

import uvicorn

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)

from app.config import Config

config = Config()

# Seed settings.json from .env on first run if settings.json is empty
def _seed_settings_from_env() -> None:
    from app.storage.store import FileStore
    store = FileStore(data_dir=config.data_dir)
    store.init()
    existing = store.load_settings()
    if not existing.get("telegram_api_id") and config.telegram_api_id:
        store.save_settings(config.to_settings_dict())
        logging.getLogger("startup").info(
            "Auto-seeded data/settings.json from environment variables."
        )

_seed_settings_from_env()

from app.server.app import create_app

application = create_app()

if __name__ == "__main__":
    uvicorn.run(
        "app.__main__:application",
        host=config.server_host,
        port=config.server_port,
        reload=False,
        log_level="info",
    )
