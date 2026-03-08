from .auth_route import auth_bp
from .user_route import user_bp
from .movie_route import movie_bp
from .wishlist_route import wishlist_bp
from .genre_route import genre_bp
from .admin_route import admin_bp
from .tmdb_route import tmdb_bp


def register_routes(app):
    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(user_bp, url_prefix="/api/users")
    app.register_blueprint(movie_bp, url_prefix="/api/movies")
    app.register_blueprint(wishlist_bp, url_prefix="/api/wishlists")
    app.register_blueprint(genre_bp, url_prefix="/api/genres")
    app.register_blueprint(admin_bp, url_prefix="/api/admin")
    app.register_blueprint(tmdb_bp, url_prefix="/api/admin/tmdb")
