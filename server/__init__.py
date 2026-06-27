from flask import Flask

def create_app():
    """
    Application Factory to create and configure the Flask app.
    """
    # static_folder is relative to the root if app is started from root, 
    # but to be safe we can use absolute paths or rely on current working directory.
    # Flask assumes relative paths are relative to the root_path of the app.
    # We will pass static_folder='../interface' if we initialize from server folder, 
    # but typically it's run from app.py at the root, so 'interface' is fine.
    # To be perfectly safe across directories, we can do:
    import os
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    static_folder = os.path.join(base_dir, 'interface')

    app = Flask(__name__, static_url_path='', static_folder=static_folder)

    # Register Blueprints
    from .routes.api import api_bp
    from .routes.web import web_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    return app
