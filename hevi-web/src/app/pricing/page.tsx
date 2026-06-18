'use client';
import { OPricingPage } from '@helios/oui';
import { TopNav } from '@/components/TopNav';

export default function PricingPage() {
  return (
    <>
      <TopNav />
      <OPricingPage
      title="选择你的创作套餐"
      subtitle="按 credits 计费,随时升级或取消"
      plans={[
        {
          id: 'free', name: '免费版', description: '适合个人尝鲜',
          price: { monthly: 0, yearly: 0, currency: '¥' },
          cta: '开始使用',
          features: [
            { text: '每月 500 credits', included: true },
            { text: '标准画质 720p', included: true },
            { text: '基础创意辅助', included: true },
            { text: '主体库', included: false },
          ],
        },
        {
          id: 'pro', name: '专业版', description: '适合内容创作者', featured: true,
          price: { monthly: 99, yearly: 990, currency: '¥' },
          cta: '升级专业版',
          features: [
            { text: '每月 8000 credits', included: true },
            { text: '高清画质 1080p', included: true },
            { text: '全部创意辅助', included: true },
            { text: '主体库 + 一致性', included: true },
          ],
        },
        {
          id: 'studio', name: '工作室版', description: '团队 / 商用',
          price: 'custom',
          cta: '联系销售',
          features: [
            { text: '定制 credits 额度', included: true },
            { text: 'Ultra 4K 画质', included: true },
            { text: '优先渲染队列', included: true },
            { text: '团队协作', included: true },
          ],
        },
      ]}
      />
    </>
  );
}
