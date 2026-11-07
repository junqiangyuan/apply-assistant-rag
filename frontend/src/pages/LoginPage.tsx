/**
 * 登录页：独立于 BasicLayout，无侧栏 / 顶栏。
 *
 * 登录成功后回到 ?back= 指定的路径；缺失时回 /。
 */

import { useState } from 'react'
import { App as AntdApp, Button, Card, Form, Input, Typography } from 'antd'
import { LockOutlined, UserOutlined } from '@ant-design/icons'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { login } from '@/api/auth'
import { useAuthStore } from '@/stores/authStore'

const DEMO_ACCOUNT_HINT: string | undefined = import.meta.env.VITE_DEMO_ACCOUNT_HINT

interface LoginFormValues {
  username: string
  password: string
}

export function LoginPage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const setAuth = useAuthStore((s) => s.setAuth)
  const [submitting, setSubmitting] = useState(false)

  async function onFinish(values: LoginFormValues) {
    setSubmitting(true)
    try {
      const result = await login(values.username, values.password)
      setAuth(result.token, result.user)
      message.success(`欢迎回来，${result.user.displayName}`)
      navigate(searchParams.get('back') || '/', { replace: true })
    } catch {
      // 拦截器已经弹过 message.error，这里只兜异常防止抛到 UI
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div
      style={{
        minHeight: '100vh',
        display: 'grid',
        placeItems: 'center',
        background:
          'linear-gradient(135deg, #f5f7fb 0%, #e6efff 100%)',
        padding: 24,
      }}
    >
      <Card style={{ width: 360 }} variant="borderless">
        <Typography.Title level={3} style={{ textAlign: 'center', marginBottom: 24 }}>
          留学申请助手
        </Typography.Title>
        <Form<LoginFormValues>
          layout="vertical"
          onFinish={onFinish}
          initialValues={{ username: '', password: '' }}
          autoComplete="off"
        >
          <Form.Item
            name="username"
            label="用户名"
            rules={[{ required: true, message: '请输入用户名' }]}
          >
            <Input prefix={<UserOutlined />} placeholder="用户名" autoFocus />
          </Form.Item>
          <Form.Item
            name="password"
            label="密码"
            rules={[{ required: true, message: '请输入密码' }]}
          >
            <Input.Password prefix={<LockOutlined />} placeholder="密码" />
          </Form.Item>
          <Form.Item style={{ marginBottom: 8 }}>
            <Button type="primary" htmlType="submit" loading={submitting} block>
              登录
            </Button>
          </Form.Item>
        </Form>
        {/* 演示环境通过 VITE_DEMO_ACCOUNT_HINT 展示只读体验账号；未配置时不展示任何账号信息 */}
        {DEMO_ACCOUNT_HINT && (
          <Typography.Paragraph
            type="secondary"
            style={{ marginTop: 8, marginBottom: 0, fontSize: 12, textAlign: 'center' }}
          >
            {DEMO_ACCOUNT_HINT}
          </Typography.Paragraph>
        )}
      </Card>
    </div>
  )
}
