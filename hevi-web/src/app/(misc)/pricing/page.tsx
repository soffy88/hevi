import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '公测期免费 · hevi',
  description: 'hevi 公测期全部功能免费，不开放支付。每天 5 条成片、单条 ≤60 秒、同时 1 个任务。',
};

const rules = [
  ['价格', '公测期免费，不接支付、不扣费'],
  ['新用户', '注册即赠送体验额度'],
  ['每日成片', '每个账号每天最多 5 条'],
  ['单条时长', '每条成片最长 60 秒'],
  ['并发任务', '同一账号同时最多 1 个任务'],
  ['正式收费', '收费前将提前通知，并公布价格与退款规则'],
];

export default function PricingPage() {
  return (
    <main className="legal-page">
      <p className="legal-page__eyebrow">HEVI / BETA</p>
      <h1>公测期免费</h1>
      <p className="legal-page__meta">更新日期：2026-11-09</p>
      <p className="legal-page__lead">
        当前处于公测期：全部功能免费开放，不接支付。正式收费前会提前通知，不会自动扣费。
      </p>
      <section>
        <h2>公测规则</h2>
        <div className="legal-page__body">
          <ul>
            {rules.map(([label, value]) => (
              <li key={label}>
                <strong>{label}：</strong>
                {value}
              </li>
            ))}
          </ul>
        </div>
      </section>
      <section>
        <h2>超出上限时</h2>
        <p>
          系统会在提交前返回中文提示（今日次数已用完 / 单条超过 60 秒 / 已有任务进行中），不会扣费。
          今日剩余次数显示在创作页与画布顶栏。
        </p>
      </section>
      <p className="legal-page__footer-note">
        运营主体：微亚人工智能有限公司 · 联系：ceo@aiinote.com · 适用中华人民共和国法律。
      </p>
    </main>
  );
}
