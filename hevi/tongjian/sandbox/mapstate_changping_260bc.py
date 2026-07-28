"""Q5 全环 · 前260 长平前夕 MapState(真实资产,非废品)。

坐标编制口径见 output/mapstate_registry/changping_260bc_research_notes.md。
投影沿用 453 图(lon100–125,lat28–45),势力多边形 P0 示意,色一律取 force_colors 注册表。
evidence_tier ≈ E2–E3(P0 示意,非 GIS)。R1:疆界溯源本矢量,不发明。

产物落 output/mapstate_registry/:MapState json + 校对 SVG + 校对 PNG。
"""

from __future__ import annotations

from pathlib import Path

from hevi.tongjian.map_state import (
    CityMark,
    FissureLine,
    ForcePolygon,
    MapState,
    River,
    render_map_state_png,
    render_map_state_svg,
)

OUT = Path("/data/soffy/projects/hevi/output/mapstate_registry")


def build_changping_260bc() -> MapState:
    return MapState(
        state_id="cn_260bc_changping",
        era_label="前260 长平前夕(秦赵对峙)",
        date=-260,
        note="长平之战前夕七雄。秦最大(吞巴蜀/汉中/河东/郢),楚东迁(失郢),韩缩,上党被秦切。E2–E3。",
        forces=[
            # 秦:关中+巴蜀+汉中+河东,西与西南最大
            ForcePolygon(
                force_id="qin",
                label_at=(108.5, 34.2),
                rings=[
                    [
                        (103.0, 30.5),
                        (106.0, 29.2),
                        (108.5, 31.0),
                        (110.5, 33.0),
                        (111.8, 35.5),
                        (111.5, 37.8),
                        (109.5, 38.2),
                        (106.5, 36.0),
                        (104.0, 34.0),
                        (102.5, 32.0),
                    ]
                ],
            ),
            # 赵:北方,邯郸/晋阳/代
            ForcePolygon(
                force_id="zhao",
                label_at=(113.5, 38.3),
                rings=[
                    [
                        (112.0, 36.8),
                        (114.8, 36.2),
                        (116.6, 38.2),
                        (115.2, 41.0),
                        (112.6, 40.6),
                        (111.6, 38.4),
                    ]
                ],
            ),
            # 韩:缩至新郑/颍川一隅(上党将脱离)
            ForcePolygon(
                force_id="han",
                label_at=(113.4, 34.3),
                rings=[
                    [
                        (112.4, 33.4),
                        (114.4, 33.7),
                        (114.0, 35.0),
                        (112.7, 35.1),
                    ]
                ],
            ),
            # 魏:大梁/河内/河东残(黄河两岸)——东移与韩错开,免中央红/金糊成一团(phase4 修正)
            ForcePolygon(
                force_id="wei",
                label_at=(115.2, 35.2),
                rings=[
                    [
                        (114.0, 35.4),
                        (115.6, 35.7),
                        (116.6, 34.9),
                        (116.0, 33.8),
                        (114.6, 33.9),
                        (113.9, 34.6),
                    ]
                ],
            ),
            # 楚:失郢东迁,淮河+江东
            ForcePolygon(
                force_id="chu",
                label_at=(116.5, 31.2),
                rings=[
                    [
                        (113.3, 32.6),
                        (116.8, 33.0),
                        (120.6, 31.2),
                        (120.2, 28.4),
                        (116.0, 28.3),
                        (113.4, 30.2),
                    ]
                ],
            ),
            # 齐:山东
            ForcePolygon(
                force_id="qi",
                label_at=(118.4, 36.6),
                rings=[
                    [
                        (116.4, 35.0),
                        (120.6, 35.4),
                        (121.2, 38.0),
                        (117.8, 38.6),
                        (116.4, 37.0),
                    ]
                ],
            ),
            # 燕:幽燕东北
            ForcePolygon(
                force_id="yan",
                label_at=(117.8, 40.8),
                rings=[
                    [
                        (115.4, 39.0),
                        (120.0, 38.8),
                        (123.0, 41.4),
                        (118.8, 43.0),
                        (115.4, 41.2),
                    ]
                ],
            ),
            # 周:洛邑弹丸(灰阶 tier)
            ForcePolygon(
                force_id="zhou",
                label_at=(112.4, 34.6),
                rings=[
                    [
                        (112.1, 34.4),
                        (112.8, 34.4),
                        (112.8, 34.9),
                        (112.1, 34.9),
                    ]
                ],
            ),
        ],
        fissures=[
            # 上党争地:韩/赵间预置裂线(秦即将切走的跳板)
            FissureLine(
                between=("han", "zhao"),
                preset=True,
                points=[(112.3, 35.3), (112.8, 35.9), (113.1, 36.6)],
            ),
        ],
        rivers=[
            River(
                name="黄河",
                width=2.8,
                points=[
                    (103.5, 36.0),
                    (107.0, 37.5),
                    (110.5, 37.8),
                    (111.5, 35.2),
                    (113.5, 34.9),
                    (116.0, 35.4),
                    (118.5, 37.2),
                    (119.5, 37.6),
                ],
            ),
            River(
                name="长江",
                width=2.5,
                points=[
                    (104.0, 29.5),
                    (108.0, 30.4),
                    (112.0, 30.2),
                    (115.5, 30.0),
                    (118.5, 31.2),
                    (121.0, 31.6),
                ],
            ),
        ],
        cities=[
            CityMark(name="长平", lon=112.9, lat=35.8, force_id="zhao"),  # 战点
            CityMark(name="邯郸", lon=114.5, lat=36.6, force_id="zhao"),
            CityMark(name="晋阳", lon=112.5, lat=37.9, force_id="zhao"),
            CityMark(name="咸阳", lon=108.7, lat=34.3, force_id="qin"),
            CityMark(name="新郑", lon=113.7, lat=34.4, force_id="han"),
            CityMark(name="大梁", lon=114.3, lat=34.8, force_id="wei"),
            CityMark(name="寿春", lon=116.8, lat=32.6, force_id="chu"),
            CityMark(name="临淄", lon=118.3, lat=36.8, force_id="qi"),
            CityMark(name="蓟", lon=116.4, lat=39.9, force_id="yan"),
        ],
    )


def main():
    ms = build_changping_260bc()
    OUT.mkdir(parents=True, exist_ok=True)

    print("同屏撞色复判(§6.2b 邻接规则):")
    for c in ms.clashes():
        print(f"  {c['pair']} 色距={c['color_dist']} 相邻={c['adjacent']} → {c['verdict']}")
    blocking = ms.blocking_clashes()
    print("  须解决(色近且相邻):", blocking or "无 ✓")

    (OUT / "cn_260bc_changping.json").write_text(ms.model_dump_json(indent=2), encoding="utf-8")
    (OUT / "cn_260bc_changping_proof.svg").write_text(
        render_map_state_svg(ms, draw_labels=True), encoding="utf-8"
    )
    render_map_state_png(ms).save(OUT / "cn_260bc_changping_proof.png")

    print("势力质心断言锚点(A1/B2/B3 免费坐标):")
    for fid, t in ms.centroid_targets().items():
        print(f"  {t['name']}({fid}): px={t['px']} frac={t['frac']} 注册色rgb={t['expected_rgb']}")
    print("产物 ->", OUT)


if __name__ == "__main__":
    main()
