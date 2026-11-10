export const metadata = { title: '致谢与第三方署名 · HEVI' };

const ITEMS = [
  {
    name: 'anidoodle',
    author: 'Alex Greenshpun',
    url: 'https://github.com/alexgreensh/anidoodle',
    license: 'Apache License 2.0',
    note: '32 种代码手绘风格、绘制过程片、代码作曲与确定性渲染。HEVI 内置引擎（third_party/anidoodle），保留 LICENSE/NOTICE；使用 playwright 后端，不装 Remotion 适配器、不下载可选音色包。引擎源码未改，HEVI 的封装与新增的死空镜读取在 hevi/anidoodle/。',
  },
  {
    name: 'handraw-style',
    author: 'yang0',
    url: 'https://github.com/yang0/handraw-style',
    license: 'MIT License with Attribution Requirement',
    note: '365+ 视觉风格、170 种排版图型、36 种主题色。HEVI 使用其结构化数据，预览图由 HEVI 自绘，不使用上游样图；在世或无法确认的参考作者姓名已按政策隐去，只保留风格特征。',
  },
  {
    name: 'BeefTV',
    author: 'glanderness',
    url: 'https://github.com/glanderness/BeefTV',
    license: 'BeefTV Source Available License 1.0（非 MIT）',
    note: '仅作早期契约级参考；未 clone、未复制代码/图片/文案/提示词，仓库与镜像不含其内容。',
  },
  {
    name: 'lanshu explainer',
    author: 'cclank',
    url: 'https://github.com/cclank',
    license: 'MIT',
    note: '讲解工具与 HyperFrames 风格套件（本地离线 runtime）。',
  },
  {
    name: 'Noto Serif / Sans CJK',
    author: 'Google / Adobe',
    url: 'https://notofonts.github.io/',
    license: 'SIL Open Font License 1.1',
    note: '封面、字幕与图解的中文字体。',
  },
];

export default function Page() {
  return (
    <main className="product-page" style={{ maxWidth: 880, margin: '0 auto', padding: '28px 18px 72px' }}>
      <p className="product-page__eyebrow">致谢 · 第三方署名</p>
      <h1>我们用到的开源与方法来源</h1>
      <p style={{ color: 'oklch(0.74 0.02 80)', lineHeight: 1.8 }}>
        以下内容按各自许可保留署名。完整清单见仓库根目录 <code>NOTICE</code> 与 <code>THIRD_PARTY_NOTICES.md</code>。
      </p>
      <div style={{ display: 'grid', gap: 14, marginTop: 22 }}>
        {ITEMS.map((item) => (
          <section key={item.name} style={{ border: '1px solid oklch(0.3 0.02 80)', borderRadius: 14, padding: 16 }}>
            <h2 style={{ margin: '0 0 6px', fontSize: 20 }}>{item.name}</h2>
            <p style={{ margin: '0 0 6px', color: 'oklch(0.82 0.02 80)' }}>
              作者/维护：{item.author} · 许可：{item.license}
            </p>
            <p style={{ margin: '0 0 8px', color: 'oklch(0.72 0.02 80)', lineHeight: 1.75 }}>{item.note}</p>
            <a href={item.url} target="_blank" rel="noopener noreferrer" style={{ color: 'oklch(0.8 0.1 85)' }}>
              {item.url}
            </a>
          </section>
        ))}
      </div>
    </main>
  );
}
