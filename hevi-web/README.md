# Hevi Web Interface

现代化的Web界面，用于AI驱动的历史题材视频创作平台。

## 功能特性

- 用户注册和登录系统
- 项目管理界面
- 视觉化的剧本编辑器
- 响应式设计，支持多种设备

## 页面结构

- `/` - 主页，介绍平台功能
- `/login` - 用户登录页面
- `/register` - 用户注册页面
- `/projects` - 项目管理页面
- `/projects/new` - 创建新项目页面

## API 路由

- `/api/login` - 用户登录接口
- `/api/register` - 用户注册接口
- `/api/projects` - 项目管理接口

## 技术栈

- Next.js 14
- React 18
- TypeScript
- Tailwind CSS
- NextAuth.js

## 开发

```bash
npm install
npm run dev
```

服务器将在 http://localhost:3001 上运行。