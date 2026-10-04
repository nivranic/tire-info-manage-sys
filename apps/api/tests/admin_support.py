"""测试夹具共享：以首个用户（管理员）身份注册当前 TestClient。

波次4权限守卫后，触发管理写的测试夹具都需要管理员会话。此前该三行
代码被复制到 11 处（第56轮圆桌 R3 发现），现收敛于此。行为测试
（test_auth_accounts）不用本 helper——它测注册行为本身，参数与断言灵活。

口令为模块级运行时随机（Mimosa 约束：测试口令不得写字面量）；需要回登
同一账户的用例引用 ADMIN_PASSWORD。
"""
import secrets

ADMIN_PASSWORD = secrets.token_urlsafe(12)


def register_admin(client, username='admin', password=None):
    response = client.post('/v1/auth/register',
                           json={'username': username, 'password': password or ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return response.json()
