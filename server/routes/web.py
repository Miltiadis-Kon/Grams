from flask import Blueprint, jsonify, send_from_directory
from server.services import db

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def index():
    return send_from_directory('interface', 'index.html')

@web_bp.route('/recipes_db.json')
def get_db():
    try:
        data = db.get_all()
        # Make sure all macros are rounded to nearest int in memory/response
        for recipe in data.values():
            if 'macros' in recipe:
                m = recipe['macros']
                recipe['macros'] = {
                    "protein": int(round(m.get("protein", 0))),
                    "carbs": int(round(m.get("carbs", 0))),
                    "fats": int(round(m.get("fats", 0))),
                    "calories": int(round(m.get("calories", 0)))
                }
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
