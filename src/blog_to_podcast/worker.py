"""Private Container App entry point for Summary Generation Jobs."""

from blog_to_podcast.runtime import run_worker

if __name__ == "__main__":
    run_worker()
