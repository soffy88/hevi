import type { Metadata } from 'next';

export const metadata: Metadata = {
  title: '隐私政策 · hevi',
  description:
    '微亚人工智能有限公司 hevi 隐私政策：收集范围、第三方处理者、AI 生成内容标识、保存期限、账号注销与投诉渠道。',
};

const sections: Array<{ title: string; body: React.ReactNode }> = [
  {
    title: '1. 适用范围与运营方',
    body: (
      <>
        本政策适用于 hevi AI 视频创作工作台（以下简称“本服务”）。本服务由
        <strong>微亚人工智能有限公司</strong>（以下简称“我们”）运营。联系与投诉邮箱：
        <a href="mailto:ceo@aiinote.com">ceo@aiinote.com</a>。本政策适用中华人民共和国法律。
      </>
    ),
  },
  {
    title: '2. 我们收集的信息',
    body: (
      <>
        账号信息：邮箱、显示名称、加密后的密码凭据、登录与安全日志。创作内容：提示词、脚本、分镜、
        上传的图片/音频/视频素材、生成结果、任务记录与画布节点状态。计费与配额信息：积分变动、
        每日成片次数、任务状态、必要的设备与访问日志。我们不会为提供服务之外的目的读取你的素材内容。
      </>
    ),
  },
  {
    title: '3. 数据保存期限',
    body: (
      <>
        成片与最终交付物默认保存 30 天；中间产物（配音、分句视频、帧图、证据图等）默认保存 7 天，
        到期后由系统自动清理。数据库每日自动备份，保留最近 7 份；已删除数据最多可能在 7 天内仍存在于
        备份中，并在备份轮换时被覆盖。访问日志与错误日志按运维需要轮换删除。法律法规另有要求的除外。
      </>
    ),
  },
  {
    title: '4. AI 生成内容标识',
    body: (
      <>
        本服务使用生成式人工智能合成视频、语音、图像与文本。所有成片均带有“AI 生成”角标，并在输出文件的
        元数据中写入 AI 生成说明。你在发布或传播生成内容时，不得删除、遮挡或伪造该标识，并应遵守适用法律
        法规关于深度合成与生成式人工智能内容标识的要求，不得冒充真实人物或真实事件。生成结果可能与真实
        人物、事件或事实不符，不构成对真实性的承诺。
      </>
    ),
  },
  {
    title: '5. 第三方处理者',
    body: (
      <>
        为完成相应功能，我们可能把完成该功能所必需的数据传递给以下第三方处理者，并要求其按约定保护数据：
        <ul>
          <li>文本模型推理与语音识别：OpenCode AI、TeamoRouter、NVIDIA NIM、OpenAI（按部署配置启用）。</li>
          <li>视频/图像生成：阿里云 DashScope、阿里云百炼（Alibaba MaaS）、fal.ai、Vidu、Runway、WaveSpeed、LibLib.tv（按你选择的功能与部署配置启用）。</li>
          <li>语音合成：本机部署的 VibeVoice、CosyVoice、Piper 在本机处理；如启用 edge-tts，则调用 Microsoft 在线语音合成服务。</li>
          <li>素材检索：Pexels、Pixabay（仅发送检索关键词）。</li>
          <li>基础设施：本机部署的 MinIO、PostgreSQL、Redis；Cloudflare 提供 CDN、安全加速与隧道，会处理访问元数据。</li>
        </ul>
        第三方素材与组件受其各自许可约束，署名、许可与使用范围以素材源页面为准。
      </>
    ),
  },
  {
    title: '6. 内容规范与投诉',
    body: (
      <>
        你不得利用本服务制作、上传或传播违法违规内容，包括侵犯他人权益、虚假信息、色情暴力、仇恨歧视、
        诈骗、侵害未成年人权益或规避内容安全机制的内容。发现违规内容或认为你的权利被侵害，可发送邮件至
        <a href="mailto:ceo@aiinote.com">ceo@aiinote.com</a> 投诉，邮件请附作品链接、问题说明与权利证明。
        我们将在收到后 15 个工作日内核查并答复；必要时先行下架或限制传播。
      </>
    ),
  },
  {
    title: '7. 未成年人',
    body: '本服务面向成年人和依法可以独立承担民事责任的用户。未成年人不得注册或使用本服务。若发现未成年人未经监护人同意使用，我们将停止服务并删除相关账号与数据。',
  },
  {
    title: '8. 非商用角色素材',
    body: '为演示与创作辅助提供的数字人、角色形象、音色与相关素材，仅限在本服务内用于非商业演示、学习与个人创作。未经权利人书面许可，不得用于商业广告、代言、付费内容、商品化或冒充真实人物。你上传的人物照片与角色素材，应确保已取得肖像权、著作权及其他必要授权。',
  },
  {
    title: '9. Cookie 与日志',
    body: '本服务使用必要的本地存储与 Cookie 维持登录状态与偏好设置。服务端会记录访问日志与错误日志用于安全审计与故障排查，并按运维需要定期轮换删除。',
  },
  {
    title: '10. 你的权利与账号注销',
    body: (
      <>
        你可以在账号设置中查看与更新账号信息，删除项目、画布与素材。需要注销账号或删除全部数据时，
        可在账号设置中发起注销，或发送邮件至
        <a href="mailto:ceo@aiinote.com">ceo@aiinote.com</a>。注销后，账号信息与关联内容按第 3 条所述周期
        清除（含最多 7 天的备份轮换期）；法律法规要求保留的除外。你也可以申请查阅、更正、复制你的个人信息，
        我们将在合理期限内响应。
      </>
    ),
  },
  {
    title: '11. 政策更新',
    body: '我们可能因功能、法规或运营变化更新本政策。重大变更将以显著方式提示；继续使用即视为接受更新后的政策。',
  },
];

export default function PrivacyPage() {
  return (
    <main className="legal-page">
      <p className="legal-page__eyebrow">HEVI / LEGAL</p>
      <h1>隐私政策</h1>
      <p className="legal-page__meta">更新日期：2026-11-09 · 版本：v1.0</p>
      <p className="legal-page__lead">
        本政策说明微亚人工智能有限公司如何收集、使用、保存与删除你的信息，以及使用 AI 生成内容与第三方素材时应注意的事项。
      </p>
      {sections.map((section) => (
        <section key={section.title}>
          <h2>{section.title}</h2>
          <div className="legal-page__body">{section.body}</div>
        </section>
      ))}
      <p className="legal-page__footer-note">
        运营主体：微亚人工智能有限公司 · 联系与投诉：ceo@aiinote.com · 适用中华人民共和国法律。
      </p>
    </main>
  );
}
