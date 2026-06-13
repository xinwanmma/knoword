"""认证端点测试。"""

import pytest
from httpx import AsyncClient


class TestRegister:
    """注册测试。"""

    @pytest.mark.asyncio
    async def test_register_success(self, client):
        resp = await client.post("/api/auth/register", json={
            "username": "newuser",
            "email": "new@test.com",
            "password": "pass123456",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["username"] == "newuser"

    @pytest.mark.asyncio
    async def test_register_duplicate_username(self, client):
        await client.post("/api/auth/register", json={
            "username": "dup_test",
            "email": "dup1@test.com",
            "password": "pass123456",
        })
        resp = await client.post("/api/auth/register", json={
            "username": "dup_test",
            "email": "dup2@test.com",
            "password": "pass123456",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_register_short_password(self, client):
        resp = await client.post("/api/auth/register", json={
            "username": "shortpw",
            "email": "short@test.com",
            "password": "123",
        })
        assert resp.status_code == 422  # validation error


class TestLogin:
    """登录测试。"""

    @pytest.mark.asyncio
    async def test_login_success(self, client):
        await client.post("/api/auth/register", json={
            "username": "logintest",
            "email": "login@test.com",
            "password": "pass123456",
        })
        resp = await client.post("/api/auth/login", json={
            "username": "logintest",
            "password": "pass123456",
        })
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client):
        await client.post("/api/auth/register", json={
            "username": "wrongpwtest",
            "email": "wrongpw@test.com",
            "password": "pass123456",
        })
        resp = await client.post("/api/auth/login", json={
            "username": "wrongpwtest",
            "password": "wrongpass",
        })
        assert resp.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        resp = await client.post("/api/auth/login", json={
            "username": "nonexistent",
            "password": "pass123456",
        })
        assert resp.status_code == 401


class TestAuthMe:
    """获取当前用户测试。"""

    @pytest.mark.asyncio
    async def test_get_me_with_token(self, auth_client):
        resp = await auth_client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["username"] == "testuser"

    @pytest.mark.asyncio
    async def test_get_me_without_token(self, client):
        resp = await client.get("/api/auth/me")
        assert resp.status_code == 403  # no credentials
