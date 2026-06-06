"""Service entry point — placeholder until Next.js dashboard integration is wired up."""
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("ai-worker-frame started (awaiting message queue integration)")


if __name__ == "__main__":
    main()
