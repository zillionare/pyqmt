"""qmt-server package."""

def create_app():
    from qmt_server.app import create_app as _create_app

    return _create_app()


__all__ = ["create_app"]
