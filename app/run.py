"""
Parrhesepstein — Entry point (porta 5001)
"""
import sys
import os

os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Ensure the parent directory is in sys.path so 'app' package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

application = create_app()

if __name__ == '__main__':
    application.run(debug=True, port=5001, threaded=True)
