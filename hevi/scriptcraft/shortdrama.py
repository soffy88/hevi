"""Short-drama mode: master plan, 10-episode outline, episode 1 beats + script.

The generator is deterministic: the same topic always produces the same plan.
It is a scaffold a writer (or a free local LLM) can replace line by line; the
checks do not care who wrote the words, only that the structure is shootable.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .causality import check_causality
from .characters import build_cast_card, check_characters
from .filmability import check_filmability
from .names import pick_names
from .premise import evaluate_premise
from .text import REACTION_ONLY, RESULT_WORDS, estimate_seconds

CLIFFHANGER_TYPES = ("生死", "揭一半", "反击第一下", "更大危机", "身份逼近", "选择题")
HOOK_TYPES = ("冲突", "悬念", "危机", "身份", "反差")

BLUEPRINTS: dict[str, dict[str, Any]] = {
    "revenge": {
        "genre": "都市复仇",
        "route": "复仇",
        "trigger": "收到一份当年被藏起来的原始文件",
        "goal": "在公开场合拿回本该属于自己的署名和股权",
        "stakes": "家人的手术费和最后的住处一起没了",
        "prop": "原始合同",
        "secret": "当年签字的人不是她，真正的受益人一直藏在幕后",
        "place": "发布会后台",
        "power": "能把每一份文件的细节记到页码",
        "sell": "被夺走一切的人，在最后一天把证据缝进了婚纱",
        "hook_action": "{lead}把婚纱内衬撕开，取出缝在里面的{prop}，放在窗口。",
        "plight_action": "{lead}把离婚协议推到窗口，工作人员拿起印章。",
        "conflict_action": "{villain}推门进来，把一份股权转让书拍在柜台上。",
        "conflict2_action": "{villain}伸手去夺{prop}，{lead}先一步把{prop}攥进掌心。",
        "reversal_action": "{lead}把手机屏幕转向{villain}，按下播放键。",
        "cliff_action": "{lead}掀开协议最后一页，露出一行被涂掉的签名。",
        "events": [
            "公开场合被夺走署名，{lead}只拿走一份复印件",
            "发现{prop}上的签名顺序不对",
            "{villain}用家人的手术排期逼{lead}撤诉",
            "{ally}送来当年会议的签到表，但少了一页",
            "{lead}假装妥协，在签约前要求公开对质",
            "对质现场播放录音，{villain}第一次失态",
            "录音被判剪辑，{lead}反而背上伪造证据的指控",
            "{lead}用{pow}核对页码，找到被抽走的那一页",
            "{villain}抛出{secret}，想把{lead}的身世一起毁掉",
            "{lead}把原始文件和签到表一起投到大屏，{villain}当场被带走",
        ],
        "payoffs": [
            "{lead}当场拿到项目署名确认书",
            "{lead}拍到{prop}的签署页，锁进银行保险箱",
            "{lead}把手术费转账记录摆到桌上，{villain}的威胁失效",
            "{lead}拿到签到表复印件，发现被撕掉的是关键一页",
            "{lead}让{ally}把对质时间写进直播预告",
            "录音在大屏上播出，{villain}的合作方当场离席",
            "{lead}被带走问话，但留下一份备份给{ally}",
            "{lead}用页码比对证明文件被抽页",
            "{lead}当众念出{secret}，把主动权抢回来",
            "原始文件投屏，{villain}被带走，{lead}签下新合同",
        ],
        "cliffhangers": [
            ("身份逼近", "{villain}看着{lead}手里的{prop}，叫出了她另一个名字"),
            ("揭一半", "签到表最后一页被撕掉，只剩半个指纹"),
            ("更大危机", "医院打来电话：手术排期被取消"),
            ("反击第一下", "{lead}把录音笔放在桌上，按下录音键"),
            ("选择题", "{villain}给出选择：撤诉，或看着家人被赶出去"),
            ("揭一半", "录音里出现第三个人的声音，{lead}脸色停住"),
            ("生死", "{lead}被反锁在资料室，门外有人拧动钥匙"),
            ("反击第一下", "{lead}把页码对照表发给在场所有记者"),
            ("身份逼近", "{villain}当众说出{secret}，全场看向{lead}"),
            ("更大危机", "警车停在门口，但走下来的人先走向{lead}"),
        ],
    },
    "injustice": {
        "genre": "现实悬疑",
        "route": "悬疑",
        "trigger": "一段被剪过的监控视频传上网",
        "goal": "在天亮前证明自己没做过那件事",
        "stakes": "被当成凶手带走，家里人再也抬不起头",
        "prop": "监控硬盘",
        "secret": "视频里被删掉的那七秒，才是真正的事发经过",
        "place": "小区门岗",
        "power": "对时间和路线有近乎偏执的记忆",
        "sell": "救了人的人，被一段视频变成了推人的人",
        "hook_action": "{lead}把湿透的外卖箱放在地上，手机里正播放自己被指认的视频。",
        "plight_action": "{lead}把当晚的配送路线截图递给{witness}，手指停在 21:47。",
        "conflict_action": "{villain}带着两名保安堵住门岗，要求{lead}当场交出手机。",
        "conflict2_action": "{villain}把一张打印的截图拍在桌上，截图里{lead}的手伸向孩子。",
        "reversal_action": "{lead}从外卖箱夹层里取出{prop}，插进门岗的读卡器。",
        "cliff_action": "{lead}点开视频最后七秒，画面里出现第三个人的鞋。",
        "events": [
            "{lead}救下孩子，却被一段剪过的视频指认为推人者",
            "物业拒绝提供完整监控，只给一张截图",
            "{villain}在网上悬赏，{lead}的工牌被曝光",
            "{ally}找到当晚的另一路摄像头，但硬盘被人取走",
            "{lead}用配送路线反推时间，发现视频少了七秒",
            "孩子母亲改口，说当时看见的是另一只手",
            "{villain}放出第二段视频，把{lead}钉死成惯犯",
            "{lead}在门岗读卡器里恢复出{prop}的缓存",
            "{villain}承认剪过视频，但说是为了保住物业的声誉",
            "{lead}把完整七秒投到小区大屏，孩子自己指认了真正的人",
        ],
        "payoffs": [
            "{lead}拿到孩子母亲的现场录音",
            "{lead}把物业的拒绝回复截图存证",
            "{lead}的工牌被解冻，平台恢复接单",
            "{lead}找到另一路摄像头的编号",
            "{lead}画出时间线，缺口正好七秒",
            "孩子母亲当场改口，围观的人开始动摇",
            "{lead}被平台停单，但拿到第二段视频的原始文件",
            "{lead}从缓存里恢复出七秒画面",
            "{villain}的录音被完整播放，物业方沉默",
            "孩子指认真正的人，{lead}当场被解开手环",
        ],
        "cliffhangers": [
            ("生死", "孩子从楼上坠下，{lead}的手还停在半空"),
            ("揭一半", "物业经理说完整监控还在，但硬盘刚被人取走"),
            ("更大危机", "{lead}的工牌被人肉曝光，站点门口围满人"),
            ("反击第一下", "{lead}把时间线截图发到业主群"),
            ("身份逼近", "孩子母亲盯着{lead}问：你那天为什么会在那栋楼"),
            ("选择题", "{villain}给出条件：删视频，或让平台永久封号"),
            ("反击第一下", "{lead}把第二段视频的原始文件交给{ally}"),
            ("揭一半", "缓存里恢复出的七秒，只有一只鞋和半句话"),
            ("身份逼近", "{villain}当众说{secret}，所有人看向{lead}"),
            ("更大危机", "警车停在门口，先下来的却是平台法务"),
        ],
    },
    "family": {
        "genre": "家庭情感",
        "route": "情感",
        "trigger": "发现家里人一直瞒着一件旧事",
        "goal": "在老人离开之前把这件事问清楚",
        "stakes": "余生都带着误会，连最后一面都错过",
        "prop": "旧照片",
        "secret": "老人一直知道真相，只是替所有人扛着",
        "place": "老屋客厅",
        "power": "记得家里每一件旧物的位置",
        "sell": "一家人守着一间老屋，谁都不肯先说那句真话",
        "hook_action": "{lead}把{prop}从衣柜顶层取下来，照片背面写着一个陌生的名字。",
        "plight_action": "{lead}把药盒按日期排好，{elder}的床位空着。",
        "conflict_action": "{villain}把房产证放进包里，说房子已经挂出去了。",
        "conflict2_action": "{lead}把{prop}放到桌上，指着背面的名字。",
        "reversal_action": "{elder}从里屋走出来，把一张存折放在照片旁边。",
        "cliff_action": "{lead}翻开存折，第一页的日期是{secret}那天。",
        "events": [
            "{lead}在旧照片背面发现陌生名字",
            "{villain}要卖老屋，{lead}不同意",
            "{elder}的病情加重，{villain}借机要求签字",
            "{lead}找到当年的邻居，邻居只说了一半",
            "{villain}拿出遗嘱，遗嘱上没有{lead}的名字",
            "{lead}发现遗嘱日期在{elder}住院之后",
            "{villain}承认改过遗嘱，但说是为了还债",
            "{elder}醒来说出{secret}，{villain}当场沉默",
            "{lead}把老屋钥匙交给{villain}，换回遗嘱原件",
            "一家人坐在客厅吃完最后一顿饭，{lead}把照片放回原处",
        ],
        "payoffs": [
            "{lead}拿到照片背面的名字和日期",
            "{lead}把卖房合同拍照留存",
            "{lead}让医生出具{elder}的意识评估",
            "{lead}拿到邻居的录音，确认当年有人来过",
            "{lead}发现遗嘱签名笔迹不对",
            "{lead}调出住院记录，证明签字当天{elder}在抢救",
            "{villain}承认改遗嘱，债主被{lead}请到现场",
            "{elder}说出{secret}，{villain}把房产证放回桌上",
            "{lead}用钥匙换回遗嘱原件",
            "老屋留下，{lead}和{villain}在饭桌上第一次好好说话",
        ],
        "cliffhangers": [
            ("悬念", "{lead}在照片背面看见一个从没听过的名字"),
            ("揭一半", "邻居说当年那件事，只说了半句就关门"),
            ("更大危机", "{villain}把卖房合同拍在桌上，买家明天就来"),
            ("反击第一下", "{lead}把遗嘱复印件发给所有亲戚"),
            ("身份逼近", "{villain}说{lead}根本不是这个家的人"),
            ("选择题", "{elder}让{lead}选：要房子，还是要真相"),
            ("反击第一下", "{lead}把住院记录放在遗嘱旁边"),
            ("揭一半", "{elder}说{secret}，但只说了前半句"),
            ("身份逼近", "{villain}拿出另一份遗嘱，签名是{lead}的"),
            ("更大危机", "老屋门口来了搬家公司，{lead}挡在门前"),
        ],
    },
    "workplace": {
        "genre": "职场逆袭",
        "route": "男频",
        "trigger": "发现项目数据被人改过",
        "goal": "在汇报会上把假数据换回真的",
        "stakes": "背锅被开除，团队半年的奖金全没",
        "prop": "原始报表",
        "secret": "改数据的人就在汇报名单里",
        "place": "会议室",
        "power": "能一眼看出报表里不合逻辑的小数点",
        "sell": "全组都在等裁员名单，只有他发现数据是假的",
        "hook_action": "{lead}把两份报表并排放在桌上，同一行的小数点位置不一样。",
        "plight_action": "{lead}把工牌翻过来，背面贴着团队的合照。",
        "conflict_action": "{villain}把裁员名单拍在桌上，{lead}的名字在最后一行。",
        "conflict2_action": "{lead}把{prop}推到投影仪下面，要求当场对数。",
        "reversal_action": "{lead}点开后台日志，修改记录停在一个熟悉的账号。",
        "cliff_action": "{villain}伸手拔掉投影线，会议室的门同时被推开。",
        "events": [
            "{lead}发现报表小数点被人改过",
            "{villain}用裁员名单逼{lead}闭嘴",
            "{lead}把原始报表备份到自己的硬盘",
            "{ally}被调走，{lead}失去唯一证人",
            "{lead}在电梯里遇到审计，但只来得及说一句",
            "审计进场，{villain}把责任推给{lead}",
            "{lead}用{pow}还原修改时间线",
            "{villain}删掉后台日志，{lead}拿出离线备份",
            "老板要求当天给结论，{lead}只有十分钟",
            "{lead}在汇报会上把假数据换回真的，{villain}当场被停职",
        ],
        "payoffs": [
            "{lead}截下原始报表的版本号",
            "{lead}把裁员名单拍照存档",
            "{lead}拿到原始报表的离线备份",
            "{lead}把{ally}的交接记录留作证据",
            "{lead}把审计的名片收进兜里",
            "{lead}当场指出三处对不上的数字",
            "{lead}还原出修改账号和时间",
            "{lead}用离线备份证明日志被删",
            "{lead}把十分钟汇报压缩成三页",
            "假数据被换回，{villain}停职，{lead}接管项目",
        ],
        "cliffhangers": [
            ("反差", "全组都在等裁员名单，{lead}却在看小数点"),
            ("揭一半", "修改记录的账号，属于一个已经离职的人"),
            ("更大危机", "{villain}把裁员名单贴到公告栏"),
            ("反击第一下", "{lead}把两份报表的对照图发进项目群"),
            ("身份逼近", "审计问{lead}：你为什么不早说"),
            ("选择题", "{villain}让{lead}选：保团队，还是保自己"),
            ("反击第一下", "{lead}把修改时间线投到屏幕上"),
            ("揭一半", "后台日志被删，只剩一条恢复记录"),
            ("更大危机", "老板要求当天出结论，否则整组解散"),
            ("更大危机", "会议室门被推开，进来的人手里拿着另一份报表"),
        ],
    },
    "suspense": {
        "genre": "循环悬疑",
        "route": "悬疑",
        "trigger": "发现今天和昨天一模一样",
        "goal": "在循环结束前找到那个重复的人",
        "stakes": "永远困在同一天，看着同一个人消失",
        "prop": "值班表",
        "secret": "重复的不是时间，是有人每天在重演同一件事",
        "place": "深夜自习室",
        "power": "能记住每一天的细微差别",
        "sell": "所有人都走出了自习室，只有他记得昨天也发生过",
        "hook_action": "{lead}把{prop}翻到昨天那一页，日期和今天完全相同。",
        "plight_action": "{lead}把手机时间举到管理员面前，管理员没有抬头。",
        "conflict_action": "{villain}把门锁上，说今天谁也不能提前走。",
        "conflict2_action": "{lead}把{prop}摊在桌上，指出每一天都少了一个名字。",
        "reversal_action": "{lead}翻开管理员的抽屉，里面是七本一模一样的值班表。",
        "cliff_action": "{lead}抬头看向监控，监控里的自己正站在门外。",
        "events": [
            "{lead}发现值班表上的日期在重复",
            "管理员对昨天的记忆完全空白",
            "{lead}尝试提前离开，门从外面被锁上",
            "{ally}在桌上留下一张只有{lead}看得懂的纸条",
            "{lead}找到第七本值班表，名字每天少一个",
            "管理员承认自己在等一个人回来",
            "{lead}发现自己也是被等的人之一",
            "{villain}出现，要求{lead}留在原位不要动",
            "{lead}打破循环的规则，把值班表全部撕掉",
            "监控里的自己走进来，循环在两个人对视时停住",
        ],
        "payoffs": [
            "{lead}拍下两天的值班表对照",
            "{lead}让管理员在纸上写下日期，笔迹一样",
            "{lead}从门缝里拍到外面的锁",
            "{lead}拿到{ally}留下的纸条",
            "{lead}把七本值班表按日期排开",
            "管理员说出等人的名字，{lead}发现不是自己",
            "{lead}在名单最后一页看到自己的名字",
            "{villain}现身，{lead}把门反锁",
            "值班表被撕掉，墙上的钟第一次走动",
            "监控里的自己走进来，两个人同时开口",
        ],
        "cliffhangers": [
            ("悬念", "{lead}发现值班表上的日期和昨天一模一样"),
            ("揭一半", "管理员记得所有人，唯独不记得昨天"),
            ("更大危机", "门从外面被锁上，手机时间停在 23:59"),
            ("反击第一下", "{lead}把两天的值班表叠在一起拍照"),
            ("身份逼近", "纸条上的字迹，和{lead}自己的一模一样"),
            ("选择题", "管理员让{lead}选：留下等，还是打破规则"),
            ("反击第一下", "{lead}把七本值班表全部摊开"),
            ("揭一半", "名单最后一页，写着{lead}自己的名字"),
            ("身份逼近", "{villain}叫出{lead}另一个名字"),
            ("更大危机", "监控里的{lead}正站在门外，抬手敲门"),
        ],
    },
    "generic": {
        "genre": "都市情感",
        "route": "混合",
        "trigger": "一件本该昨天就结束的事，今天又开始了",
        "goal": "在所有人改变主意之前把话说清楚",
        "stakes": "失去最后一点可以相信的人",
        "prop": "旧手机",
        "secret": "所有人都在替同一个人保守秘密",
        "place": "街角小店",
        "power": "记得别人说过每一句话的日期",
        "sell": "一件小事，把所有人的体面都撕开一条缝",
        "hook_action": "{lead}把{prop}放在柜台上，屏幕停在三年前的一条短信。",
        "plight_action": "{lead}把零钱一枚一枚码好，柜台上只剩一个人的影子。",
        "conflict_action": "{villain}推门进来，把一张欠条压在{prop}旁边。",
        "conflict2_action": "{lead}把欠条翻过来，背面写着一个不该出现的名字。",
        "reversal_action": "{lead}点开旧手机，播放一段三年前的语音。",
        "cliff_action": "{lead}把语音停在最后一秒，{villain}的手停在门把上。",
        "events": [
            "{lead}被一件旧事重新找上门",
            "{villain}拿出欠条，要求当天结清",
            "{lead}发现欠条背面的名字不是自己的",
            "{ally}承认当年替人签过字",
            "{lead}用{pow}对上三年前的日期",
            "{villain}改口，说欠条只是复印件",
            "{lead}找到原件，发现金额被人改过",
            "{villain}说出{secret}，把责任推给不在场的人",
            "{lead}把语音放到最大声，街坊都听见了",
            "原件和语音对上，{villain}当场把欠条撕了",
        ],
        "payoffs": [
            "{lead}拿到旧手机里的第一条短信",
            "{lead}把欠条拍照存证",
            "{lead}查出欠条背面的名字",
            "{lead}让{ally}把当年的签字过程写下来",
            "{lead}把日期对照表摊在柜台上",
            "{lead}拿到欠条复印件的来源",
            "{lead}找到原件并拍下金额",
            "{lead}把{secret}当众说开",
            "语音被街坊听见，{villain}无法再抵赖",
            "欠条被撕，{lead}拿回自己的名字",
        ],
        "cliffhangers": [
            ("悬念", "{lead}在旧手机里看到一条三年前的短信"),
            ("揭一半", "欠条背面的名字，{lead}从来没听过"),
            ("更大危机", "{villain}说今天不结清就搬东西"),
            ("反击第一下", "{lead}把欠条和短信放在一起拍照"),
            ("身份逼近", "{ally}问{lead}：你到底是谁"),
            ("选择题", "{villain}让{lead}选：认账，还是让{ally}背"),
            ("反击第一下", "{lead}把日期对照表贴在门口"),
            ("揭一半", "原件上的金额，比欠条多一个零"),
            ("身份逼近", "{villain}当众说出{secret}"),
            ("更大危机", "街坊围过来，{lead}却找不到{ally}"),
        ],
    },
}

KEYWORDS = {
    "revenge": ("离婚", "股权", "公司", "公章", "婚纱", "复仇", "背叛", "夺回", "总裁", "豪门"),
    "injustice": ("外卖", "监控", "冤枉", "推人", "骑手", "证据", "清白", "网暴", "指认", "救"),
    "family": ("养老", "老屋", "父亲", "母亲", "遗嘱", "房子", "病", "家人", "遗产", "照片"),
    "workplace": ("职场", "裁员", "报表", "数据", "项目", "老板", "实习", "汇报", "审计", "公司"),
    "suspense": ("循环", "重复", "自习室", "监控", "失踪", "同一天", "管理员", "钥匙", "悬疑", "消失"),
}


def _finding(rule: str, severity: str, message: str, ref: str = "") -> dict[str, Any]:
    return {"rule": rule, "severity": severity, "message": message, "ref": ref}


def select_blueprint(topic: str, genre: str = "") -> tuple[str, dict[str, Any]]:
    text = f"{topic} {genre}"
    best = ("generic", 0)
    for key, words in KEYWORDS.items():
        score = sum(1 for word in words if word in text)
        if score > best[1]:
            best = (key, score)
    return best[0], BLUEPRINTS[best[0]]


def _fill(template: str, slots: dict[str, str]) -> str:
    out = template
    for key, value in slots.items():
        out = out.replace("{" + key + "}", value)
    return out


def _seed(topic: str) -> int:
    return int(hashlib.sha256(topic.encode("utf-8")).hexdigest()[:8], 16)


def derive_characters(topic: str, blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    names = pick_names(topic, 4)
    lead, villain, ally, witness = names
    markers = [
        ["左手腕一道旧烫伤", "深蓝色工牌", "洗到发白的帆布鞋"],
        ["右手无名指的戒痕", "黑色皮手套", "左眉尾一颗小痣"],
        ["圆框眼镜", "磨破的袖口", "随身旧录音笔"],
        ["红色围巾", "手里总拿着一串钥匙", "鞋跟磨偏"],
    ]
    return [
        {
            "id": "c1", "name": lead, "role": "主角",
            "bio": f"在{blueprint['place']}附近讨生活，习惯把每件事记在纸上，因为吃过没证据的亏。",
            "relations": [{"target": villain, "type": "曾经的合伙人/对手"}],
            "defect": "太相信白纸黑字，低估了人会当场翻脸",
            "arc": "从只想保住自己，到敢在所有人面前把真相摊开",
            "visual_markers": markers[0],
            "outfit": {"top": "深灰外套", "bottom": "牛仔裤", "shoes": "旧帆布鞋"},
            "personality": "克制、记仇、说到做到",
            "voice": {"description": "偏低、语速稳，急起来反而更轻", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "深灰外套"},
        },
        {
            "id": "c2", "name": villain, "role": "反派",
            "bio": f"在{blueprint['place']}有资源、有人脉，习惯用规则压人而不是动手。",
            "relations": [{"target": lead, "type": "夺走主角东西的人"}],
            "defect": "傲慢，永远相信对方不敢把事闹大",
            "arc": "从稳操胜券，到被自己的规则反噬",
            "visual_markers": markers[1],
            "outfit": {"top": "黑色西装", "bottom": "深色西裤", "shoes": "皮鞋"},
            "personality": "体面、强硬、输不起",
            "voice": {"description": "中低音，句尾压得很稳", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "黑色西装"},
        },
        {
            "id": "c3", "name": ally, "role": "重要配角",
            "bio": f"和{lead}一起熬过最难的时候，手里有一点{villain}不知道的资源。",
            "relations": [{"target": lead, "type": "朋友/同事"}],
            "defect": "怕事，帮人之前总要先算一遍代价",
            "arc": "从躲在后面，到愿意站出来作证",
            "visual_markers": markers[2],
            "outfit": {"top": "浅色衬衫", "bottom": "休闲裤", "shoes": "运动鞋"},
            "personality": "谨慎、心软、关键时刻靠得住",
            "voice": {"description": "偏亮，语速快", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "浅色衬衫"},
        },
        {
            "id": "c4", "name": witness, "role": "配角",
            "bio": f"在{blueprint['place']}做最不起眼的工作，看见了别人没注意到的细节。",
            "relations": [{"target": lead, "type": "旁观者/证人"}],
            "defect": "习惯性沉默，怕惹麻烦",
            "arc": "从只说一半，到把看见的全说出来",
            "visual_markers": markers[3],
            "outfit": {"top": "工作马甲", "bottom": "深色长裤", "shoes": "防滑鞋"},
            "personality": "寡言、观察细",
            "voice": {"description": "轻、慢，带一点口音", "piper_voice": "zh_CN-huayan-medium.onnx"},
            "state": {"pose": "站", "location": "", "prop": "", "outfit": "工作马甲"},
        },
    ]


def build_master_plan(
    *,
    topic: str,
    blueprint_key: str,
    blueprint: dict[str, Any],
    characters: list[dict[str, Any]],
    slots: dict[str, str],
) -> dict[str, Any]:
    lead, villain, ally, witness = [c["name"] for c in characters]
    fill = {**slots, "lead": lead, "villain": villain, "ally": ally, "witness": witness}
    return {
        "title": topic,
        "sell_point": _fill(blueprint["sell"], fill),
        "genre": blueprint["genre"],
        "route": blueprint["route"],
        "core_hook": _fill(blueprint["hook_action"], fill),
        "lead": {
            "name": lead,
            "identity": f"{blueprint['place']}附近的普通人",
            "goal": _fill(blueprint["goal"], fill),
            "defect": "太相信白纸黑字",
            "arc": "从自保到公开对质",
        },
        "villain": {
            "name": villain,
            "identity": f"掌握{blueprint['place']}资源的人",
            "goal": f"让{lead}闭嘴并拿走最后一点筹码",
        },
        "mainline": f"{lead}因为{blueprint['trigger']}，必须{blueprint['goal']}，否则{blueprint['stakes']}。",
        "relation_line": f"{lead}与{villain}曾是{('合伙人' if blueprint_key in {'revenge', 'workplace'} else '熟人')}；{ally}是唯一还愿意帮{lead}的人；{witness}看见了关键一幕。",
        "trump_card": _fill(blueprint["secret"], fill),
        "core_payoff": _fill(blueprint["payoffs"][-1], fill),
        "reversal_path": [
            f"第2–3集：{ _fill(blueprint['events'][1], fill) }",
            f"第6集：{ _fill(blueprint['events'][5], fill) }",
            f"第9集：{ _fill(blueprint['events'][8], fill) }",
        ],
        "escalation": {
            "early": _fill(blueprint["events"][2], fill),
            "mid": _fill(blueprint["events"][5], fill),
            "late": _fill(blueprint["events"][8], fill),
        },
        "ending": _fill(blueprint["payoffs"][-1], fill),
        "why_vertical": "单集一个公开冲突，手机竖屏能看清手部证据和脸部反应；每集结尾停在未解决的动作上。",
        "format": "series",
        "episode_count": 10,
        "episode_seconds": 95,
    }


def build_episode_outline(
    *,
    blueprint: dict[str, Any],
    slots: dict[str, str],
    characters: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    lead, villain, ally, witness = [c["name"] for c in characters]
    fill = {**slots, "lead": lead, "villain": villain, "ally": ally, "witness": witness}
    rows: list[dict[str, Any]] = []
    previous_type = ""
    for index in range(10):
        cliff_type, cliff_text = blueprint["cliffhangers"][index]
        if cliff_type == previous_type and index >= 2:
            cliff_type = CLIFFHANGER_TYPES[(CLIFFHANGER_TYPES.index(cliff_type) + 1) % len(CLIFFHANGER_TYPES)]
        previous_type = cliff_type
        opening = "冷开场：直接给结果" if index == 0 else f"承接上集卡点（{blueprint['cliffhangers'][index - 1][0]}）"
        rows.append({
            "ep": index + 1,
            "opening_connects": opening,
            "connector": ("", "所以", "但是", "所以", "但是", "所以", "但是", "所以", "但是", "所以")[index],
            "core_event": _fill(blueprint["events"][index], fill),
            "payoff": _fill(blueprint["payoffs"][index], fill),
            "cliffhanger_type": cliff_type,
            "cliffhanger": _fill(cliff_text, fill),
            "is_major_reversal": index + 1 in {6, 9},
            "escalation_level": 1 + index // 3,
        })
    return rows


def build_ep1_beat_sheet(*, blueprint: dict[str, Any], slots: dict[str, str], characters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    lead, villain, _, witness = [c["name"] for c in characters]
    fill = {**slots, "lead": lead, "villain": villain, "witness": witness}
    return [
        {"row": 1, "module": "暴击", "start_s": 0, "end_s": 3,
         "beat": _fill(blueprint["hook_action"], fill), "hook_type": "冲突"},
        {"row": 2, "module": "主角处境", "start_s": 3, "end_s": 25,
         "beat": _fill(blueprint["plight_action"], fill), "hook_type": "身份"},
        {"row": 3, "module": "公开具体冲突", "start_s": 25, "end_s": 52,
         "beat": _fill(blueprint["conflict_action"], fill), "hook_type": "冲突"},
        {"row": 4, "module": "冲突升级", "start_s": 52, "end_s": 70,
         "beat": _fill(blueprint["conflict2_action"], fill), "hook_type": "危机"},
        {"row": 5, "module": "翻盘信号露一角", "start_s": 70, "end_s": 88,
         "beat": _fill(blueprint["reversal_action"], fill), "hook_type": "反差"},
        {"row": 6, "module": "卡点+钩子台词", "start_s": 88, "end_s": 95,
         "beat": _fill(blueprint["cliff_action"], fill), "hook_type": "悬念"},
    ]


def _line(speaker: str, text: str, kind: str = "said", duration_s: float | None = None, **extra: Any) -> dict[str, Any]:
    return {
        "speaker": speaker,
        "kind": kind,
        "text": text,
        "duration_s": round(max(
            float(duration_s) if duration_s is not None else 0.0,
            estimate_seconds(text, cps=4.5),
        ), 1),
        **extra,
    }


def build_ep1_script(
    *,
    topic: str,
    blueprint: dict[str, Any],
    slots: dict[str, str],
    characters: list[dict[str, Any]],
) -> dict[str, Any]:
    lead, villain, ally, witness = [c["name"] for c in characters]
    fill = {**slots, "lead": lead, "villain": villain, "ally": ally, "witness": witness}
    prop = slots["prop"]
    place = blueprint["place"]
    scenes = [
        {
            "scene_no": 1,
            "scene_id": "sc_01",
            "name": f"{place}门口",
            "location": f"{place}门口",
            "int_ext": "外",
            "day_night": "日",
            "characters_present": [lead, witness],
            "coverage": ["大全景", "正打", "反打"],
            "lighting": {"direction": "侧逆光", "hardness": "硬", "warmth": "冷", "contrast": "高"},
            "beats": [
                {
                    "beat_id": "sc_01_b01",
                    "duration_s": 3,
                    "action": ["△ " + _fill(blueprint["hook_action"], fill)],
                    "dialogue": [
                        _line(lead, "今天这章，谁也别想替我盖。", "inner", 2.4),
                    ],
                },
                {
                    "beat_id": "sc_01_b02",
                    "duration_s": 22,
                    "action": [
                        "△ " + _fill(blueprint["plight_action"], fill),
                        f"△ {lead}把{prop}往窗口里推了两厘米，又停住。",
                    ],
                    "dialogue": [
                        _line(witness, f"{lead}，过了今天，这事就定了。", "said", 2.6),
                        _line(lead, "我知道，所以才今天来。", "said", 2.4),
                    ],
                },
            ],
        },
        {
            "scene_no": 2,
            "scene_id": "sc_02",
            "name": f"{place}大厅",
            "location": f"{place}大厅",
            "int_ext": "内",
            "day_night": "日",
            "characters_present": [lead, villain, witness],
            "coverage": ["大全景", "正打", "反打"],
            "lighting": {"direction": "顶光", "hardness": "半硬", "warmth": "中性", "contrast": "中"},
            "beats": [
                {
                    "beat_id": "sc_02_b01",
                    "duration_s": 27,
                    "action": [
                        "△ " + _fill(blueprint["conflict_action"], fill),
                        f"△ {witness}往后退半步，把通道让出来。",
                    ],
                    "dialogue": [
                        _line(villain, f"把{prop}放下，我可以当没看见。", "said", 2.6),
                        _line(lead, "你看见什么了？", "said", 1.8),
                        _line(villain, "看见你不自量力。", "said", 2.2),
                    ],
                },
                {
                    "beat_id": "sc_02_b02",
                    "duration_s": 18,
                    "action": ["△ " + _fill(blueprint["conflict2_action"], fill)],
                    "dialogue": [
                        _line(villain, "你敢？", "said", 1.2),
                        _line(lead, "你试试。", "said", 1.2),
                    ],
                },
            ],
        },
        {
            "scene_no": 3,
            "scene_id": "sc_03",
            "name": f"{place}走廊",
            "location": f"{place}走廊",
            "int_ext": "内",
            "day_night": "日",
            "characters_present": [lead, villain],
            "coverage": ["大全景", "正打", "反打"],
            "lighting": {"direction": "侧光", "hardness": "硬", "warmth": "冷", "contrast": "高"},
            "beats": [
                {
                    "beat_id": "sc_03_b01",
                    "duration_s": 18,
                    "action": [
                        "△ " + _fill(blueprint["reversal_action"], fill),
                        f"△ {villain}的手停在半空，眼睛盯着手机。",
                    ],
                    "dialogue": [
                        _line(villain, "这段录音，你从哪来的？", "said", 2.4),
                        _line(lead, "你猜。", "said", 1.2),
                    ],
                }
            ],
        },
        {
            "scene_no": 4,
            "scene_id": "sc_04",
            "name": f"{place}门口",
            "location": f"{place}门口",
            "int_ext": "外",
            "day_night": "夜",
            "characters_present": [lead, villain],
            "coverage": ["大全景", "正打", "反打"],
            "lighting": {"direction": "路灯顶光", "hardness": "硬", "warmth": "冷", "contrast": "高"},
            "beats": [
                {
                    "beat_id": "sc_04_b01",
                    "duration_s": 7,
                    "action": ["△ " + _fill(blueprint["cliff_action"], fill)],
                    "dialogue": [
                        _line(villain, "你以为你赢了？", "said", 2.0),
                        _line(lead, "我只想拿回我的名字。", "said", 2.4),
                    ],
                }
            ],
        },
    ]
    name_to_id = {str(c["name"]): str(c["id"]) for c in characters}
    for scene in scenes:
        for beat in scene.get("beats") or []:
            for line in beat.get("dialogue") or []:
                speaker = str(line.get("speaker") or "")
                if speaker in name_to_id:
                    line["speaker_name"] = speaker
                    line["speaker"] = name_to_id[speaker]
        for cid in list(scene.get("characters_present") or []):
            if cid in name_to_id:
                scene["characters_present"].remove(cid)
                scene["characters_present"].append(name_to_id[cid])
    return {
        "title": f"{topic}·第1集",
        "logline": _fill(blueprint["sell"], fill),
        "style": "live_action",
        "aspect": "9:16",
        "duration_target_s": 95,
        "hook": {
            "first_3s_conflict": f"{lead}当众取出{prop}，{villain}伸手来夺",
            "hook_type": "冲突",
            "pass": True,
        },
        "characters": characters,
        "props": [
            {"name": prop, "size_cm": 4, "note": "可单手拿住，能放进内衬"},
            {"name": "手机", "size_cm": 15, "note": "屏幕不显示具体文字"},
            {"name": "协议", "size_cm": 30, "note": "A4 对折"},
        ],
        "new_terms": [place, prop],
        "ep1_core_characters": [name_to_id[lead], name_to_id[villain], name_to_id[witness]],
        "cliffhanger": _fill(blueprint["cliffhangers"][0][1], fill),
        "scenes": scenes,
    }


def build_ep1_review(script: dict[str, Any]) -> dict[str, Any]:
    from .review import review_document

    return review_document(script, mode="short_drama", stage="ep1")


def rhythm_findings(outline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    same_run = 1
    previous = ""
    for row in outline:
        cliff = str(row.get("cliffhanger_type") or "")
        if cliff == previous:
            same_run += 1
        else:
            same_run = 1
        previous = cliff
        if same_run >= 3:
            out.append(_finding(
                "R-CLIFF-REPEAT", "must",
                f"连续 {same_run} 集用同一类卡点「{cliff}」", f"ep{row.get('ep')}",
            ))
        payoff = str(row.get("payoff") or "")
        if not any(word in payoff for word in RESULT_WORDS):
            out.append(_finding(
                "R-PAYOFF", "must",
                f"第{row.get('ep')}集爽点没有落地成结果", f"ep{row.get('ep')}",
            ))
        if any(word in payoff for word in REACTION_ONLY) and not any(word in payoff for word in RESULT_WORDS):
            out.append(_finding(
                "R-REACTION", "must",
                f"第{row.get('ep')}集爽点写成反应（「{payoff[:12]}」），不是已发生的结果",
                f"ep{row.get('ep')}",
            ))
        if "同时" in str(row.get("core_event") or ""):
            out.append(_finding("R-ONE-CONFLICT", "must", f"第{row.get('ep')}集有两个核心冲突", f"ep{row.get('ep')}"))
        if row.get("ep", 1) >= 2 and not str(row.get("opening_connects") or "").startswith("承接上集"):
            out.append(_finding("R-OPEN", "must", f"第{row.get('ep')}集开头没有接上集卡点", f"ep{row.get('ep')}"))
        if "第" in str(row.get("cliffhanger") or "") and "集完" in str(row.get("cliffhanger") or ""):
            out.append(_finding("R-END", "must", f"第{row.get('ep')}集写了「第N集完」", f"ep{row.get('ep')}"))
    levels = [int(r.get("escalation_level") or 1) for r in outline]
    if levels and max(levels) < 3:
        out.append(_finding("R-ESCALATE", "must", "10 集没有完成前中后期升级"))
    reversals = [r for r in outline if r.get("is_major_reversal")]
    if not reversals:
        out.append(_finding("R-REVERSAL", "must", "10 集里没有 8–15 集量级的大反转"))
    return out


def ep1_findings(script: dict[str, Any], beats: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    core = [str(x) for x in script.get("ep1_core_characters") or []]
    if len(core) > 3:
        out.append(_finding("E1-CORE", "must", f"第 1 集核心人物 {len(core)} 个，超过 3 个"))
    terms = [str(x) for x in script.get("new_terms") or []]
    if len(terms) > 2:
        out.append(_finding("E1-TERMS", "must", f"第 1 集新专有名词 {len(terms)} 个，超过 2 个"))
    if any("前史" in str(s) or "世界观" in str(s) for s in script.get("scenes") or []):
        out.append(_finding("E1-PREHISTORY", "must", "第 1 集写了世界观/前史"))
    if len(beats) < 5 or len(beats) > 8:
        out.append(_finding("E1-BEATS", "must", f"第 1 集节拍表 {len(beats)} 行，应为 5–8 行"))
    else:
        modules = {str(b.get("module")) for b in beats}
        for required in ("暴击", "主角处境", "公开具体冲突", "翻盘信号露一角", "卡点+钩子台词"):
            if required not in modules and not any(required[:2] in m for m in modules):
                out.append(_finding("E1-MODULE", "must", f"第 1 集缺模块「{required}」"))
        if float(beats[0].get("end_s") or 0) > 3.01:
            out.append(_finding("E1-0-3", "must", "0–3 秒没有暴击"))
        if float(beats[-1].get("end_s") or 0) < 80:
            out.append(_finding("E1-END", "should", "结尾卡点太早，钩子会散"))
    return out


def plan_short_drama(
    *,
    topic: str,
    genre: str = "",
    route: str = "",
    episodes: int = 10,
    episode_seconds: int = 95,
    confirm: bool = False,
    mode: str = "series",
) -> dict[str, Any]:
    key, blueprint = select_blueprint(topic, genre)
    slots = {
        "prop": blueprint["prop"],
        "place": blueprint["place"],
        "secret": blueprint["secret"],
        "power": blueprint["power"],
        "pow": blueprint["power"],
    }
    characters = derive_characters(topic, blueprint)
    premise_questions = {
        "genre": blueprint["genre"],
        "identification": "被夺走东西、还被要求体面的普通人",
        "strongest_conflict": f"{blueprint['goal']}，但{villain_name(characters)}掌握所有资源",
        "best_payoff": _fill(blueprint["payoffs"][-1], {
            "lead": characters[0]["name"], "villain": characters[1]["name"],
            "ally": characters[2]["name"], "witness": characters[3]["name"],
            "prop": blueprint["prop"], "secret": blueprint["secret"],
        }),
        "secret_reversal": blueprint["secret"],
        "route": route or blueprint["route"],
    }
    premise = evaluate_premise(
        topic=topic,
        slots={
            "protagonist": f"在{blueprint['place']}被压住的普通人",
            "trigger": blueprint["trigger"],
            "goal": blueprint["goal"],
            "stakes": blueprint["stakes"],
        },
        questions=premise_questions,
        mode=mode,
    )
    master = build_master_plan(
        topic=topic, blueprint_key=key, blueprint=blueprint,
        characters=characters, slots=slots,
    )
    outline = build_episode_outline(blueprint=blueprint, slots=slots, characters=characters)
    beats = build_ep1_beat_sheet(blueprint=blueprint, slots=slots, characters=characters)
    script = build_ep1_script(topic=topic, blueprint=blueprint, slots=slots, characters=characters)
    rhythm = rhythm_findings(outline)
    ep1 = ep1_findings(script, beats)
    filmability = check_filmability(script)
    causality = check_causality(outline)
    cast_check = check_characters(characters)
    must = (
        [f for f in rhythm if f["severity"] == "must"]
        + [f for f in ep1 if f["severity"] == "must"]
        + [f for f in filmability["findings"] if f["severity"] == "must"]
        + [f for f in causality["findings"] if f["severity"] == "must"]
        + [f for f in cast_check if f["severity"] == "must"]
    )
    plan = {
        "kind": "short_drama",
        "topic": topic,
        "blueprint": key,
        "premise_gate": premise,
        "gate": {
            "stage": "story_master_plan",
            "requires_confirmation": True,
            "confirmed": bool(confirm),
            "can_continue": bool(confirm) and premise["verdict"] == "pass",
            "message": "先确认故事总盘，再写分集大纲与第 1 集。" if not confirm else "已确认。",
        },
        "master_plan": master,
        "characters": characters,
        "cast_cards": [build_cast_card(c, index=i + 1) for i, c in enumerate(characters)],
        "episode_outline": outline[:max(1, min(episodes, 30))],
        "ep1_beat_sheet": beats,
        "script": script,
        "checks": {
            "premise": premise["findings"],
            "cast": cast_check,
            "rhythm": rhythm,
            "ep1": ep1,
            "causality": causality,
            "filmability": filmability,
            "passed": not must,
            "must_count": len(must),
        },
        "review": build_ep1_review(script),
        "next": "review" if must == [] else "fix_checks",
    }
    plan["script"]["planned_episode_count"] = episodes
    plan["script"]["episode_seconds"] = episode_seconds
    return plan


def villain_name(characters: list[dict[str, Any]]) -> str:
    return characters[1]["name"] if len(characters) > 1 else "反派"


__all__ = [
    "BLUEPRINTS",
    "CLIFFHANGER_TYPES",
    "HOOK_TYPES",
    "build_ep1_beat_sheet",
    "build_ep1_review",
    "build_ep1_script",
    "build_episode_outline",
    "build_master_plan",
    "derive_characters",
    "ep1_findings",
    "plan_short_drama",
    "rhythm_findings",
    "select_blueprint",
]
