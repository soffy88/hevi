"""《我在历史现场·商鞅变法》——人工撰稿首集(2026-07-27,soffy 认可"比自动出片好很多")。

立意一条线:变法真正难的不是写出新法,而是让一个谁都不信官府的国家重新相信「说到做到」。
南门立木立信 → 刑太子傅立威 → 十年强秦收束。这份 spec 同时是"填好的模板"——新一集照抄替换即可。

审核(免费,查叙事分组+反打镜序):
    from hevi.tongjian.episodes.shangyang_bianfa import EPISODE
    from hevi.tongjian.authored_episode import summarize_episode_structure
    print(summarize_episode_structure(EPISODE))
出片:produce_authored_episode(EPISODE, ...);driver 见 scratchpad/run_story.py($80 熔断)。
"""

from hevi.tongjian.authored_episode import AuthoredBeat, AuthoredCharacter, AuthoredEpisode

EPISODE = AuthoredEpisode(
    title="我在历史现场·商鞅变法",
    thesis="变法之难不在写新法,而在让谁都不信官府的国家重新相信『说到做到』;信立则法行。",
    raw_text=(
        "战国之世,秦僻处西陲,又穷又弱,为东方诸侯所卑,会盟不与。秦孝公发愤图强,下求贤令:"
        "宾客群臣有能出奇计强秦者,吾且尊官与之分土。卫鞅自魏入秦,说孝公以强国之术。守旧老臣"
        "甘龙、杜挚难之,卫鞅曰:治世不一道,便国不法古。孝公善之,任卫鞅为左庶长,卒定变法之令:"
        "废井田、开阡陌,奖军功,置县制,平斗桶权衡丈尺。令既具未布,恐民不信,乃立三丈之木于国都"
        "市南门,募民能徙置北门者予五十金。有一人徙之,辄予五十金,以明不欺。太子犯法,卫鞅曰法之"
        "不行自上犯之,刑其傅公子虔。行之十年,秦民大悦,道不拾遗,山无盗贼,家给人足,勇于公战,"
        "秦以富强。事在战国秦栎阳,夯土宫殿高台城郭、城门市井,无飞檐斗拱无砖券。"
    ),
    intro=(
        "今天,我们回到两千三百多年前的秦国栎阳,看一场真实发生过的变法——商鞅变法。"
        "它最难的地方,从来不是想出新法子,而是怎么让一个谁都不信官府的国家,重新相信四个字:说到做到。"
    ),
    characters=[
        AuthoredCharacter(
            id="C_wei",
            name="卫鞅",
            appearance="卫鞅,束发木簪单髻无冠,深褐色交领深衣束布带,锐利坚毅的中年男子,手持竹简",
            voice="zh-CN-YunjianNeural",
        ),
        AuthoredCharacter(
            id="C_gong",
            name="秦孝公",
            appearance="秦孝公,战国秦国君,玄色深衣束发戴冠,威严沉毅的青年君主,端坐高台御座",
            voice="zh-CN-YunyeNeural",
        ),
        AuthoredCharacter(
            id="C_gan",
            name="甘龙",
            appearance="秦国守旧老臣甘龙,玄色深衣束发戴冠,须发花白,神情持重保守的老者",
            voice="zh-CN-YunxiNeural",
        ),
        AuthoredCharacter(
            id="C_qian",
            name="公子虔",
            appearance="秦国公子虔,太子傅,玄色深衣束发戴冠,面色阴沉的中年贵族",
            voice="zh-CN-YunxiaNeural",
        ),
    ],
    locations={
        "J1": "战国秦栎阳都城外,夯土城墙,风沙苍凉的西部边城,白日天光",
        "BIAN": "战国秦栎阳宫大殿,夯土玄柱高台御座,朝堂,无飞檐斗拱无砖券",
        "J2": "战国秦栎阳宫朝堂,夯土玄柱高台,案几竹简,无飞檐斗拱无砖券",
        "LIMU": "战国秦栎阳城南门市集空地,夯土城墙,商肆幡旗,白日天光",
        "J3": "战国秦栎阳城南门市集空地,夯土城墙,商肆幡旗,白日天光",
        "XING": "战国秦栎阳宫朝堂,夯土玄柱高台,无飞檐斗拱无砖券",
        "J4": "战国秦栎阳城郭全景,夯土高台宫殿与田野阡陌,黄昏暖光",
        "J5": "战国秦栎阳宫朝堂空景,夯土玄柱高台,肃穆,无飞檐斗拱无砖券",
    },
    beats=[
        # ① 讲解·背景(推演)
        AuthoredBeat(
            kind="narration",
            scene="J1",
            text=(
                "战国那会儿,秦国窝在最西边,又穷又弱,东边的诸侯开会,都懒得叫上它。"
                "年轻的秦孝公咽不下这口气,贴出一张求贤令:谁能让秦国强起来,我就跟他共享这个国家。"
                "一个叫卫鞅的年轻人,听说了,从魏国一路西行,进了秦国。"
            ),
            visual_prompt=(
                "战国秦栎阳都城夯土城门外,一张木牍求贤告示钉在城门木柱上,风沙漫过苍凉的西部边城,"
                "远处夯土城墙低矮斑驳,写实历史正剧空镜,无人"
            ),
        ),
        # ② 演绎·廷辩(卫鞅↔甘龙,孝公裁)
        AuthoredBeat(
            kind="dialogue",
            scene="BIAN",
            speaker="C_wei",
            target="C_gong",
            text=(
                "治理天下,从来没有一条一成不变的老路。只要能让国家强,就不必死守古法。"
                "当年商汤、周武没照搬旧规矩,照样得了天下;夏桀、商纣一分礼法都没改,反倒亡了国。"
            ),
        ),
        AuthoredBeat(
            kind="dialogue",
            scene="BIAN",
            speaker="C_gan",
            target="C_wei",
            text=(
                "话不能这么说。顺着百姓的老习惯去教化,不费劲就能成;守着旧法度去治理,官吏熟、百姓也安稳。"
                "你这一改,天下人非议论纷纷不可。"
            ),
        ),
        AuthoredBeat(
            kind="dialogue",
            scene="BIAN",
            speaker="C_wei",
            target="C_gan",
            text=(
                "普通人只图守着眼前的安稳,读书人只认自己听过的道理。这样的人,让他们照章办事可以,"
                "要跟他们商量规矩以外的大事,不行。"
            ),
        ),
        AuthoredBeat(
            kind="dialogue",
            scene="BIAN",
            speaker="C_gong",
            target="C_wei",
            text="好。就照你说的办。",
        ),
        # ③ 讲解·变法内容(埋"信"的扣)
        AuthoredBeat(
            kind="narration",
            scene="J2",
            text=(
                "孝公拜卫鞅做了左庶长,新法一条条定了下来:废掉井田,放开田界任人开垦;"
                "凭军功给爵位;把地方改成郡县来管;连量粮食的斗、称东西的秤,都统一了标准。"
                "可法令写好了,卫鞅却迟迟不敢公布。他怕的是同一件事——老百姓,压根不信官府。"
            ),
            visual_prompt=(
                "战国秦朝堂室内,一卷竹简法令摊开在木案几上,一名深衣官员执笔伏案,"
                "身后夯土玄柱高台肃穆,侧光,写实历史正剧,无飞檐斗拱"
            ),
        ),
        # ④ 演绎·立木(卫鞅单人宣令)
        AuthoredBeat(
            kind="dialogue",
            scene="LIMU",
            speaker="C_wei",
            text="谁能把这根木头,从南门扛到北门,赏五十金。",
        ),
        # ⑤ 讲解·立木结果(payoff,配图治"枯树小院"错配)
        AuthoredBeat(
            kind="narration",
            scene="J3",
            text=(
                "一根三丈来高的大木头,就这么立在都城南门的空地上。赏钱从十金一路加到五十金,"
                "人群围着,议论着,却没人敢上手——天上不会掉馅饼,这里头准有诈。"
                "直到一个汉子将信将疑地扛起木头,一步步搬到了北门。卫鞅当场,把五十金如数点给了他。"
                "一座城,就这么记住了一件从没见过的事:官府这一回,说到做到。"
            ),
            visual_prompt=(
                "战国秦栎阳城南门市集空地,一根三丈高的原木木杆孤零零竖立在夯土地面上,"
                "一群穿深衣的秦国百姓远远围观议论,白日天光,商肆幡旗,夯土城墙,写实历史正剧"
            ),
        ),
        # ⑥ 演绎·刑太子傅(卫鞅宣判,立威)
        AuthoredBeat(
            kind="dialogue",
            scene="XING",
            speaker="C_wei",
            target="C_qian",
            text=(
                "新法推行才一年,太子就犯了法。太子是国君的继承人,不能动刑;"
                "可法令行不通,病根往往出在上头。既然如此——就处罚教导太子的人。公子虔,依法用刑。"
            ),
        ),
        # ⑦ 讲解·十年结果(收束立意)
        AuthoredBeat(
            kind="narration",
            scene="J4",
            text=(
                "这一下,满朝上下再没人敢把新法当摆设。就这么推行了十年:秦国路上丢了东西没人捡,"
                "山里绝了盗贼,家家有余粮,人人愿意为国家上阵拼命。当年那个被诸侯瞧不起的秦国,"
                "一步步强了起来。而这一切的起点,不过是南门口那根——搬得动、也真兑得了现的木头。"
            ),
            visual_prompt=(
                "战国秦栎阳城郭全景俯瞰,夯土高台宫殿巍峨,城外田野阡陌纵横,一派安定富足的边城气象,"
                "黄昏暖光,写实历史正剧空镜"
            ),
        ),
        # ⑧ 臣光曰(实录:司马光原评,白话转述)
        AuthoredBeat(
            kind="commentary",
            scene="J5",
            text=(
                "《资治通鉴》的作者司马光,为这件事写下一句评语:诚信,是君主最大的法宝。"
                "商鞅身处你争我夺的战国,尚且不敢忘了用诚信去聚拢百姓,何况治理太平天下的人呢?"
            ),
            tier="实录",
            cite="资治通鉴·周纪二",
            visual_prompt=(
                "战国秦栎阳宫朝堂空景,夯土玄柱高台肃穆,一卷《资治通鉴》竹简意象,庄重,写实历史正剧"
            ),
        ),
    ],
)
