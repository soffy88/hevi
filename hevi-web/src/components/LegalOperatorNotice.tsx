/**
 * 运营方信息占位（S9）。合规页上线前必须由运营方本人填写，这里不编造任何
 * 主体名称、地址、备案号或联系方式；未确认字段统一显示“待运营方确认”。
 */
export function LegalOperatorNotice() {
  return (
    <section className="legal-page__operator" aria-label="运营方信息（待确认）">
      <p className="legal-page__operator-title">
        运营方信息待运营方确认（占位，未填写任何真实主体信息）
      </p>
      <dl>
        <dt>运营主体</dt><dd>待运营方确认</dd>
        <dt>统一社会信用代码</dt><dd>待运营方确认</dd>
        <dt>注册地址</dt><dd>待运营方确认</dd>
        <dt>联系邮箱 / 电话</dt><dd>待运营方确认</dd>
        <dt>主要司法辖区</dt><dd>待运营方确认</dd>
        <dt>ICP / 公安 / 算法备案号</dt><dd>待运营方确认</dd>
      </dl>
    </section>
  );
}
