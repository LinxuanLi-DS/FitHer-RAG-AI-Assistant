"""Local profile API tests using a disposable in-memory SQLite database."""

import os
import secrets
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from api.models.user import Base, User, get_db

with patch.dict(os.environ, {"SECRET_KEY": secrets.token_hex(32)}):
    with patch("api.models.user.init_db"):
        from api.routers.users import create_token, router


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            session.add_all([
                User(id=1, username="demo-owner", age=22),
                User(id=2, username="demo-other", age=29),
            ])
            session.commit()

        def override_db():
            with Session(self.engine) as session:
                yield session

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_db] = override_db
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.owner_headers = {"Authorization": f"Bearer {create_token(1)}"}

    def test_profile_routes_require_a_token(self):
        self.assertEqual(self.client.get("/users/profile/1").status_code, 401)
        response = self.client.put("/users/profile", params={"user_id": 1}, json={"age": 23})
        self.assertEqual(response.status_code, 401)

    def test_profile_routes_restrict_other_users(self):
        response = self.client.get("/users/profile/2", headers=self.owner_headers)
        self.assertEqual(response.status_code, 403)
        response = self.client.put(
            "/users/profile", params={"user_id": 2}, json={"age": 23}, headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 403)

    def test_owner_can_read_and_update_profile(self):
        response = self.client.put(
            "/users/profile", params={"user_id": 1}, json={"age": 23}, headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/users/profile/1", headers=self.owner_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["age"], 23)

        response = self.client.put(
            "/users/save-profile", json={"age": 24}, headers=self.owner_headers,
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.get("/users/me", headers=self.owner_headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["age"], 24)


if __name__ == "__main__":
    unittest.main()
