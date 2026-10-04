"""测试夹具共享：以首个用户（管理员）身份注册当前 TestClient。

波次4权限守卫后，触发管理写的测试夹具都需要管理员会话。此前该三行
代码被复制到 11 处（第56轮圆桌 R3 发现），现收敛于此。行为测试
（test_auth_accounts）不用本 helper——它测注册行为本身，参数与断言灵活。
"""


def register_admin(client, username='admin', password='fixture-admin-pw'):
    response = client.post('/v1/auth/register', json={'username': username, 'password': password})
    assert response.status_code == 200, response.text
    return response.json()
