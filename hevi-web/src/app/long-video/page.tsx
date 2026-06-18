import { redirect } from 'next/navigation';
// 长视频生成已并入首页(简单生成页),此路由重定向
export default function Page() {
  redirect('/');
}
