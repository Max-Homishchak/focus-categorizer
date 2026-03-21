import asyncio
import logging
import sys

from categorizer import MessageCategorizer
from config import Config
from report_generator import ReportGenerator
from telegram_extractor import TelegramExtractor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")


async def main() -> None:
    config = Config()

    errors = config.validate()
    if errors:
        log.error("Missing configuration:")
        for e in errors:
            log.error("  • %s", e)
        log.error("Copy .env.example → .env and fill in the values.")
        sys.exit(1)

    log.info("=" * 52)
    log.info("  Telegram Channel Categorizer")
    log.info("=" * 52)
    log.info("Model: %s | Batch size: %d | Max messages/user: %d",
             config.model, config.users_per_batch, config.max_messages_per_user)

    # Step 1: Telegram extraction
    log.info("[1/3] Extracting messages from Telegram...")
    extractor = TelegramExtractor(config)
    users_by_id = await extractor.extract_messages()

    if not users_by_id:
        log.error("No messages found. Check CHANNEL_USERNAME and try again.")
        sys.exit(1)

    # Step 2: Categorize with LLM
    log.info("[2/3] Categorizing users with %s...", config.model)
    categorizer = MessageCategorizer(config)
    results = categorizer.categorize_users(users_by_id)

    # Step 3: Generate reports
    log.info("[3/3] Writing reports...")
    generator = ReportGenerator(config)
    generator.generate(results)

    log.info("Done! Open %s/report.html in your browser.", config.output_dir)


if __name__ == "__main__":
    asyncio.run(main())
