"""Topic-grounded preschool storyboards and fail-closed child-safety rules."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

STAGES = ["greeting", "problem", "try", "solve", "recap", "action", "goodbye", "interaction"]

KIDS_TOPIC_STORYBOARDS: dict[str, dict[str, Any]] = {
    "fox_turn_taking": {
        "title": "小狐狸学会轮流", "theme": "轮流与分享", "hero": "小狐狸", "friend": "小兔子",
        "pages": [
            {"title": "一起玩球吧", "scene_key": "fox_share", "beats": [
                {"stage": "greeting", "text": "嗨，小朋友！今天和小狐狸、小兔子一起玩球吧！"},
                {"stage": "problem", "text": "小兔子也想玩，可是球只有一颗，怎么办呢？"}]},
            {"title": "轮流来试试", "scene_key": "turn_taking", "beats": [
                {"stage": "try", "text": "小狐狸先抱着球，朋友们在等，它想到了一个办法。"},
                {"stage": "solve", "text": "我们分享着轮流玩吧！你一下，我一下，大家都能玩。"}]},
            {"title": "记住小办法", "scene_key": "fox_share", "beats": [
                {"stage": "recap", "text": "记住啦，分享和轮流就是排好队，一个接一个来。"},
                {"stage": "action", "text": "现在把玩具轻轻传给朋友，也请朋友传给你。"}]},
            {"title": "下次再一起玩", "scene_key": "turn_taking", "beats": [
                {"stage": "goodbye", "text": "今天玩得真开心，再见啦，小朋友！"},
                {"stage": "interaction", "text": "下次你想和谁一起玩球呢？记得告诉身边的大人。"}]},
        ],
    },
    "brush_teeth": {
        "title": "为什么要刷牙", "theme": "温和的日常刷牙习惯", "hero": "小熊", "friend": "小狐狸",
        "pages": [
            {"title": "早上好，刷牙啦", "scene_key": "brush_teeth", "beats": [
                {"stage": "greeting", "text": "早上好，小朋友！和小熊一起刷牙吧！"},
                {"stage": "problem", "text": "小熊吃完点心，牙齿上有小小的碎屑，怎么办呢？"}]},
            {"title": "轻轻刷一刷", "scene_key": "brush_teeth", "beats": [
                {"stage": "try", "text": "小熊拿起牙刷，挤一点牙膏，轻轻开始刷。"},
                {"stage": "solve", "text": "上面刷一刷，下面刷一刷，里外慢慢刷到。"}]},
            {"title": "每天的小习惯", "scene_key": "brush_teeth", "beats": [
                {"stage": "recap", "text": "记住啦，刷牙要认真，上下里外都刷到。"},
                {"stage": "action", "text": "刷完漱漱口，请大人陪你把牙齿刷干净。"}]},
            {"title": "明天也见", "scene_key": "stars_nature", "beats": [
                {"stage": "goodbye", "text": "谢谢小熊陪我们刷牙，再见啦，明天见！"},
                {"stage": "interaction", "text": "今天刷过牙了吗？记得告诉身边的大人。"}]},
        ],
    },
    "tidy_toys": {
        "title": "玩具回家啦", "theme": "温和的收纳习惯", "hero": "小狐狸", "friend": "小兔子",
        "pages": [
            {"title": "你好，小朋友", "scene_key": "tidy_up", "beats": [
                {"stage": "greeting", "text": "你好，小朋友！我们和小狐狸一起收玩具吧！"},
                {"stage": "problem", "text": "地上的积木和小球散开了，玩具该回哪里呢？"}]},
            {"title": "试着分一分", "scene_key": "tidy_up", "beats": [
                {"stage": "try", "text": "小狐狸拿起一个积木，再看看旁边的玩具盒。"},
                {"stage": "solve", "text": "积木住进积木盒，小球住进小篮子，各回各的家。"}]},
            {"title": "记住办法", "scene_key": "fox_share", "beats": [
                {"stage": "recap", "text": "记住啦，玩完玩具，我们一起把它们送回家。"},
                {"stage": "action", "text": "请你挑一件玩具，和大人一起放回原来的地方。"}]},
            {"title": "再见啦", "scene_key": "stars_nature", "beats": [
                {"stage": "goodbye", "text": "地板变整齐啦，谢谢你帮忙，再见，小朋友！"},
                {"stage": "interaction", "text": "你最喜欢收好哪一件玩具呢？说给大人听吧！"}]},
        ],
    },
    "crosswalk": {
        "title": "学会安全过马路", "theme": "在大人陪伴下安全过马路", "hero": "小猫", "friend": "小兔子",
        "pages": [
            {"title": "和大人一起出发", "scene_key": "crosswalk", "beats": [
                {"stage": "greeting", "text": "嗨，小朋友！今天和小猫跟着大人学过马路。"},
                {"stage": "problem", "text": "小猫走到路口，看到车子经过，怎么办呢？"}]},
            {"title": "先停一停", "scene_key": "crosswalk", "beats": [
                {"stage": "try", "text": "小猫先停在路边，牵好大人的手，一起看看信号灯。"},
                {"stage": "solve", "text": "等绿灯亮了，再牵着大人的手走人行横道。"}]},
            {"title": "安全小口诀", "scene_key": "crosswalk", "beats": [
                {"stage": "recap", "text": "记住啦，过马路要停一停、看信号、牵好手。"},
                {"stage": "action", "text": "请你和大人一起找找人行横道，跟着信号走。"}]},
            {"title": "再见啦", "scene_key": "crosswalk", "beats": [
                {"stage": "goodbye", "text": "跟着大人安全过马路，真棒！再见，小朋友！"},
                {"stage": "interaction", "text": "过马路时你会牵谁的手呢？记得告诉身边的大人。"}]},
        ],
    },
    "wash_hands": {
        "title": "为什么要洗手", "theme": "吃东西前和玩耍后洗手", "hero": "小熊", "friend": "小狐狸",
        "pages": [
            {"title": "你好，小朋友", "scene_key": "hand_washing", "beats": [
                {"stage": "greeting", "text": "你好，小朋友！今天和小熊一起学洗手吧！"},
                {"stage": "problem", "text": "小熊玩完积木，准备吃点心，手该怎么办呢？"}]},
            {"title": "小泡泡来帮忙", "scene_key": "hand_washing", "beats": [
                {"stage": "try", "text": "小熊先打开水龙头，弄湿双手，再抹一点肥皂。"},
                {"stage": "solve", "text": "手心手背搓一搓，指缝也搓一搓，再用清水冲干净。"}]},
            {"title": "记住好习惯", "scene_key": "hand_washing", "beats": [
                {"stage": "recap", "text": "记住啦，吃东西前要洗手，玩完也要洗手。"},
                {"stage": "action", "text": "请你和大人一起洗洗手，把小手擦干。"}]},
            {"title": "下次见", "scene_key": "hand_washing", "beats": [
                {"stage": "goodbye", "text": "小手干净啦，谢谢你一起练习，再见，小朋友！"},
                {"stage": "interaction", "text": "吃点心前，你准备先做什么呢？记得告诉身边的大人。"}]},
        ],
    },
}

BLOCKED_KIDS_TERMS = (
    "巴菲特", "暴利", "毁灭", "生死威胁", "武器", "鲜血", "恐怖", "鬼怪",
    "杀人", "惩罚", "羞辱", "坏孩子", "笨蛋", "投资回报", "复利效应",
    "复利", "资产", "投资", "财富", "股票", "暴力", "危险模仿", "自残",
    "毒品", "酗酒", "可口可乐", "迪士尼", "抖音", "广告", "收益率", "金融杠杆",
    "深入机制分析", "底层运行机制", "成人的顶级智慧", "宇宙法则", "投资收益",
)
REQUIRED_TEXT_MARKERS = {
    "greeting": ("小朋友",),
    "problem": ("怎么办", "要怎么办", "呢？"),
    "try": ("拿起", "先", "想到了"),
    "solve": ("办法", "轮流", "刷", "住进", "绿灯", "冲干净", "搓一搓"),
    "recap": ("记住",),
    "action": ("你", "请", "一起"),
    "goodbye": ("再见",),
    "interaction": ("？", "吗？", "呢？"),
}
CHARACTERS = ("小狐狸", "小兔子", "小猫", "小熊", "小狗", "小星星")
VISIBLE_TEXT_KEYS = {"title", "text", "note", "subtitle", "caption", "label"}


class UnsupportedKidsTopicError(ValueError):
    """Raised when a topic is adult-oriented or has no suitable child-safe template."""


def _requested_hero(topic: str) -> str:
    """Respect the first IP character named in a multi-character topic."""
    matches = (name for name in CHARACTERS if name in topic)
    return min(matches, key=topic.index, default="")


def _replace_characters(spec: dict[str, Any], hero: str) -> None:
    default_hero = spec.get("hero", "小狐狸")
    friend = spec.get("friend", "")
    if not hero or hero == default_hero:
        return
    def swap(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: swap(item) for key, item in value.items()}
        if isinstance(value, list):
            return [swap(item) for item in value]
        if not isinstance(value, str):
            return value
        if hero == friend and friend:
            token = "__HANDDRAW_HERO__"
            return value.replace(default_hero, token).replace(friend, default_hero).replace(token, hero)
        return value.replace(default_hero, hero)
    spec["pages"] = swap(spec["pages"])
    spec["hero"] = hero


EXTENDED_KIDS_TOPICS: dict[str, dict[str, Any]] = {
    "fear_night": {
        "title": "勇敢说出怕黑的感觉", "theme": "表达害怕并找可信赖的大人陪伴", "hero": "小熊",
        "scene_key": "bear_night",
        "titles": ["晚上好，小朋友", "小小的安心办法", "记住安心口诀", "晚安，明天见"],
        "texts": [
            "小朋友，晚上好！小熊有一点怕黑，我们一起陪陪它。",
            "小熊看见房间暗下来，心里有点害怕，怎么办呢？",
            "小熊先抱好柔软的小枕头，慢慢看看熟悉的房间。",
            "柔和的小夜灯亮起来，家人也在旁边，这就是安心的办法。",
            "记住啦，觉得害怕时可以慢慢呼吸，找信任的大人陪伴。",
            "请你和身边的大人一起说说，什么会让你安心。",
            "谢谢小熊勇敢说出感受，再见啦，晚安！",
            "晚上觉得不安时，你会找谁陪伴呢？记得告诉身边的大人。",
        ],
    },
    "bedtime": {
        "title": "小星星睡前故事", "theme": "平静的睡前准备和规律作息", "hero": "小星星",
        "scene_key": "stars_nature",
        "titles": ["睡前准备好", "慢慢安静下来", "记住睡前小步骤", "晚安，好梦"],
        "texts": [
            "小朋友，晚上好！小星星来陪大家准备睡觉啦！",
            "小星星还想玩一会儿，到了睡觉时间该怎么办呢？",
            "小星星先收好故事书，穿上舒服的睡衣，再刷刷牙。",
            "听一段轻柔故事，关好小台灯，安静躺下就是好办法。",
            "记住啦，睡前收玩具、刷牙、听故事，每晚慢慢来。",
            "请你和身边的大人一起完成睡前准备，再轻轻说晚安。",
            "小星星眨眨眼，祝小朋友睡个好觉，再见啦，晚安！",
            "今晚睡觉前，你最想听哪个温柔故事呢？记得告诉身边的大人。",
        ],
    },
    "gratitude": {
        "title": "学会说谢谢", "theme": "表达感谢和体贴", "hero": "小狗",
        "scene_key": "puppy_gratitude",
        "titles": ["朋友来帮忙", "把谢谢说出来", "记住温暖的话", "谢谢你，再见"],
        "texts": [
            "小朋友，你好！小狗和朋友们今天想练习说谢谢。",
            "朋友帮小狗捡起画笔，小狗想表达感谢，该怎么办呢？",
            "小狗先看着朋友，想一想对方为自己做了什么。",
            "小狗微笑着说谢谢你，真诚表达感谢就是好办法。",
            "记住啦，别人帮助我们时，可以看着对方说谢谢。",
            "请你和身边的大人一起练习说谢谢，也听听对方的心情。",
            "朋友们互相帮助，心里暖暖的，谢谢你一起练习，再见啦！",
            "今天谁帮助过你，你想对谁说谢谢呢？记得告诉身边的大人。",
        ],
    },
    "emotion": {
        "title": "生气时学会冷静", "theme": "认识生气情绪并用安全方法平静下来", "hero": "小狐狸",
        "scene_key": "feelings",
        "titles": ["小狐狸有点生气", "试试慢慢呼吸", "记住冷静小办法", "好好说出感受"],
        "texts": [
            "小朋友，你好！小狐狸也会生气，我们来认识这种感觉。",
            "小狐狸搭好的积木倒了，它皱起眉头，生气时怎么办呢？",
            "小狐狸先停一停，把小手放在肚子上，慢慢吸气和呼气。",
            "等心情平静，再告诉朋友自己的感受，就是温柔的办法。",
            "记住啦，生气很正常，我们可以停一停、呼吸、好好说。",
            "请你和身边的大人一起练习深呼吸，再说出自己的感受。",
            "小狐狸和朋友重新搭好积木，互相理解真开心，再见啦！",
            "你生气时，什么能帮你慢慢平静下来呢？记得告诉身边的大人。",
        ],
    },
    "nature": {
        "title": "种子怎样长大", "theme": "观察种子发芽和爱护自然", "hero": "小兔子",
        "scene_key": "seed_growth",
        "titles": ["发现一粒种子", "一起照顾种子", "记住成长需要", "明天再来观察"],
        "texts": [
            "小朋友，你好！小兔子发现一粒小种子，想知道自然的秘密。",
            "种子种进土里以后，会发生什么变化呢？",
            "小兔子先给种子一点水，把花盆放在有阳光的地方。",
            "有水、有光和合适的照顾，种子慢慢发芽就是成长的办法。",
            "记住啦，观察自然要有耐心，也要温柔地照顾小植物。",
            "请你和身边的大人一起观察一株植物，看看叶子有什么变化。",
            "小兔子决定每天来看一看，感谢大自然带来的惊喜，再见啦！",
            "你见过什么小植物慢慢长大呢？记得告诉身边的大人。",
        ],
    },
    "courage": {
        "title": "试一试就有新发现", "theme": "鼓励温和尝试并允许失败", "hero": "小猫",
        "scene_key": "cat_courage",
        "titles": ["想试试新事情", "一步一步来", "记住勇敢小办法", "为努力拍拍手"],
        "texts": [
            "小朋友，你好！小猫想学一个新本领，我们陪它试一试。",
            "小猫想自己拼好拼图，第一块没放对，接下来怎么办呢？",
            "小猫先看看图片，再慢慢转动拼图，不着急也不放弃。",
            "每次只试一小步，需要时请大人帮忙，就是好办法。",
            "记住啦，勇敢学新本领可以慢慢来，做错了也能再试一次。",
            "请你和身边的大人一起挑一件安全的小事，慢慢练习。",
            "小猫为自己的努力拍拍手，也谢谢帮助它的朋友，再见啦！",
            "你最近想试着学会什么新本领呢？记得告诉身边的大人。",
        ],
    },
    "sadness": {
        "title": "难过时可以说出来", "theme": "认识难过的感受并向可信赖的人表达", "hero": "小兔子",
        "scene_key": "rabbit_sadness",
        "titles": ["小兔子有点难过", "找到陪伴和安慰", "记住表达感受", "一起慢慢开心"],
        "texts": [
            "小朋友，你好！小兔子今天有一点难过，我们陪陪它。",
            "小兔子的积木作品散开了，心里很失落，该怎么办呢？",
            "小兔子先慢慢呼吸，再把心里的感受告诉信任的朋友。",
            "朋友坐在身边认真倾听，再陪它一起重新搭建，这就是温柔的办法。",
            "记住啦，难过时可以说出来，也可以找信任的大人陪伴。",
            "请你和身边的大人一起说说心情，想想什么能给你安慰。",
            "小兔子被朋友温柔地陪伴着，心里慢慢舒服一些，再见啦！",
            "你难过的时候，想找谁说一说呢？记得告诉身边的大人。",
        ],
    },
    "apology": {
        "title": "学会说对不起", "theme": "真诚道歉、修复关系和关心他人", "hero": "小狐狸",
        "scene_key": "fox_share",
        "titles": ["不小心碰倒积木", "看看朋友的心情", "说出对不起", "一起重新开始"],
        "texts": {
            "greeting": "小朋友，你好！小狐狸和朋友今天来学一学怎样道歉。",
            "problem": "小狐狸转身时不小心碰倒了朋友的积木，怎么办呢？",
            "try": "小狐狸先停下来，看看朋友的作品，也听听朋友怎么想。",
            "solve": "小狐狸真诚地说对不起，并问朋友愿不愿意一起搭好，这是修复关系的好办法。",
            "recap": "记住啦，做错事时可以说对不起，再想办法弥补。",
            "action": "请你和身边的大人练习说对不起，也想想怎样帮助别人。",
            "goodbye": "朋友一起收好积木，愿意沟通真好，再见啦！",
            "interaction": "不小心影响朋友时，你可以怎样说呢？记得告诉身边的大人。",
        },
    },
    "friendship": {
        "title": "和朋友一起合作", "theme": "友谊、合作和轮流倾听", "hero": "小狐狸",
        "scene_key": "turn_taking",
        "titles": ["一起完成小任务", "轮流听一听", "记住合作办法", "朋友明天见"],
        "texts": [
            "小朋友，你好！小狐狸和朋友想一起完成一个小任务。",
            "两位朋友都想先选积木，怎样才能一起玩呢？",
            "小狐狸先听朋友说，朋友也认真听一听对方的想法。",
            "大家轮流选择、一起搭建，就是合作的好办法。",
            "记住啦，好朋友会轮流、会倾听，也会一起想办法。",
            "请你和身边的大人一起练习轮流说话，也听听对方的话。",
            "小狐狸和朋友完成了作品，开心地互相道谢，再见啦！",
            "和朋友一起玩时，你想怎样轮流和合作呢？记得告诉身边的大人。",
        ],
    },
}


def _build_extended_storyboard(topic: str, key: str) -> dict[str, Any]:
    """Build an 8-beat, topic-grounded preschool script with a selected hero."""
    config = EXTENDED_KIDS_TOPICS[key]
    requested_hero = _requested_hero(topic)
    hero = requested_hero or str(config["hero"])
    default_hero = str(config["hero"])
    friend = next((name for name in CHARACTERS if name != hero), "小狐狸")
    texts = config["texts"]
    if isinstance(texts, dict):
        beats = [
            {"stage": stage, "text": str(text).replace(default_hero, hero)}
            for stage, text in texts.items()
        ]
    else:
        beats = [
            {"stage": stage, "text": str(text).replace(default_hero, hero)}
            for stage, text in zip(STAGES, texts, strict=True)
        ]
    pages = [
        {
            "title": config["titles"][index],
            "scene_key": (
                "bear_night" if key in {"fear_night", "bedtime"} and hero == "小熊"
                else config["scene_key"]
            ),
            "beats": [beats[index * 2], beats[index * 2 + 1]],
        }
        for index in range(4)
    ]
    return {
        "title": topic if len(topic) <= 36 else str(config["title"]),
        "theme": config["theme"],
        "hero": hero,
        "friend": friend,
        "pages": pages,
        "topic_key": key,
        "stages": list(STAGES),
    }


def select_kids_storyboard(topic: str) -> dict[str, Any]:
    """Route to a matching child-safe template; never silently substitute a theme."""
    raw = str(topic or "").strip()
    if not raw:
        raise UnsupportedKidsTopicError("幼儿故事必须提供具体主题；未生成默认替代故事。")
    blocked = sorted(term for term in BLOCKED_KIDS_TERMS if term in raw)
    if blocked:
        raise UnsupportedKidsTopicError(f"主题不适合 2–6 岁幼儿，已拒绝生成：{', '.join(blocked)}")
    normalized = raw.lower()
    if any(word in normalized for word in ("刷牙", "牙齿", "牙膏", "口腔", "dent")):
        key = "brush_teeth"
    elif any(word in normalized for word in ("洗手", "肥皂", "洗干净双手", "handwash")):
        key = "wash_hands"
    elif any(word in normalized for word in ("过马路", "红绿灯", "人行横道", "斑马线", "交通安全")):
        key = "crosswalk"
    elif any(word in normalized for word in ("收拾", "整理", "玩具", "tidy", "clean up")):
        key = "tidy_toys"
    elif any(word in normalized for word in ("分享", "轮流", "一起玩", "玩球", "share", "turn taking")):
        key = "fox_turn_taking"
    elif any(word in normalized for word in ("不怕黑", "怕黑", "害怕", "夜晚", "夜里", "黑暗", "fear", "afraid")):
        key = "fear_night"
    elif any(word in normalized for word in ("睡前", "睡觉", "睡不着", "晚安", "bedtime", "sleep")):
        key = "bedtime"
    elif any(word in normalized for word in ("谢谢", "感谢", "感恩", "说谢谢", "gratitude", "thank you")):
        key = "gratitude"
    elif any(word in normalized for word in ("难过", "伤心", "sadness", "sad")):
        key = "sadness"
    elif any(word in normalized for word in ("对不起", "道歉", "sorry", "apology", "apologize")):
        key = "apology"
    elif any(word in normalized for word in ("生气", "发脾气", "情绪", "anger")):
        key = "emotion"
    elif any(word in normalized for word in ("种子", "植物", "自然", "发芽", "昆虫", "星星", "月亮", "nature", "science")):
        key = "nature"
    elif any(word in normalized for word in ("勇敢", "尝试", "新本领", "不放弃", "courage", "try something")):
        key = "courage"
    elif any(word in normalized for word in ("朋友", "友谊", "合作", "家人", "家人朋友", "friendship", "family")):
        key = "friendship"
    else:
        raise UnsupportedKidsTopicError(
            f"暂不支持该幼儿主题：{raw}。可选择分享/轮流、刷牙、洗手、收拾玩具、过马路、怕黑、睡前、感恩、情绪、自然、勇敢或友谊；不会套用无关模板。"
        )
    if key in EXTENDED_KIDS_TOPICS:
        spec = _build_extended_storyboard(raw, key)
    else:
        spec = deepcopy(KIDS_TOPIC_STORYBOARDS[key])
        requested_hero = _requested_hero(raw)
        _replace_characters(spec, requested_hero)
        spec["title"] = raw if len(raw) <= 36 else KIDS_TOPIC_STORYBOARDS[key]["title"]
        spec["topic_key"] = key
        spec["stages"] = list(STAGES)
    return spec


def validate_kids_on_screen_text(texts: list[str]) -> dict[str, Any]:
    """Check all user-visible overlay/title text for adult or prohibited topics."""
    visible = [str(value) for value in texts if value is not None]
    blocked = sorted({term for term in BLOCKED_KIDS_TERMS if any(term in value for value in visible)})
    return {"checked_text_count": len(visible), "blocked_terms_found": blocked, "passed": not blocked}


def _visible_texts(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if key in VISIBLE_TEXT_KEYS and isinstance(item, str):
                found.append(item)
            elif isinstance(item, (dict, list)):
                found.extend(_visible_texts(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_visible_texts(item))
    return found


def validate_kids_script(
    topic: str,
    pages: list[dict[str, Any]],
    *,
    aspect: str,
    caption_font_size: int,
    characters_per_second: float | None = None,
    audio_lufs: float | None = None,
    true_peak_dbtp: float | None = None,
    preview: bool = False,
    require_audio_measurements: bool = False,
) -> dict[str, Any]:
    """Report local rule checks; missing measurements fail closed at final gate."""
    beats = [beat for page in pages for beat in page.get("beats", [])]
    script = "\n".join(str(beat.get("text") or "") for beat in beats)
    visible_texts = [topic, *_visible_texts(pages)]
    blocked = sorted({term for term in BLOCKED_KIDS_TERMS if any(term in value for value in [script, *visible_texts])})
    stages = [str(beat.get("stage") or "") for beat in beats]
    stage_sequence_ok = preview or stages == STAGES
    missing_markers = []
    for beat in beats:
        stage = str(beat.get("stage") or "")
        markers = REQUIRED_TEXT_MARKERS.get(stage, ())
        if markers and not any(marker in str(beat.get("text") or "") for marker in markers):
            missing_markers.append(stage)
    familiar_words = any(word in script for word in (*CHARACTERS, "小朋友"))
    caption_minimum = 56 if aspect == "9:16" else 48
    lufs_finite = audio_lufs is not None and __import__("math").isfinite(float(audio_lufs))
    peak_finite = true_peak_dbtp is not None and __import__("math").isfinite(float(true_peak_dbtp))
    checks = {
        "blocked_terms_absent": not blocked,
        "stage_sequence": stage_sequence_ok,
        "stage_language_markers": not missing_markers,
        "child_facing_language": familiar_words,
        "caption_font_minimum": int(caption_font_size) >= caption_minimum,
        "pace_within_3_5_chars_per_second": (characters_per_second is not None and __import__("math").isfinite(float(characters_per_second)) and characters_per_second <= 3.5) if require_audio_measurements else (characters_per_second is None or (__import__("math").isfinite(float(characters_per_second)) and characters_per_second <= 3.5)),
        "integrated_loudness_minus_16_plus_minus_1_lufs": (lufs_finite and -17.0 <= float(audio_lufs) <= -15.0) if require_audio_measurements else (audio_lufs is None or (lufs_finite and -17.0 <= float(audio_lufs) <= -15.0)),
        "true_peak_at_or_below_minus_1_5_dbtp": (peak_finite and float(true_peak_dbtp) <= -1.5) if require_audio_measurements else (true_peak_dbtp is None or (peak_finite and float(true_peak_dbtp) <= -1.5)),
        "audio_measurements_present": (lufs_finite and peak_finite) if require_audio_measurements else True,
    }
    return {
        "schema_version": 2, "gate": "kids_anime_rule_based", "review_type": "automated_only", "human_review": "pending",
        "topic": topic, "theme": "preschool_daily_life_or_social_emotional_learning", "aspect": aspect, "preview": preview,
        "beat_count": len(beats), "stage_sequence": stages, "expected_stage_sequence": STAGES,
        "blocked_terms_found": blocked, "visible_text_checked_count": len(visible_texts),
        "missing_stage_markers": missing_markers, "characters_per_second": characters_per_second,
        "audio_lufs": audio_lufs, "true_peak_dbtp": true_peak_dbtp,
        "caption_font_size": int(caption_font_size), "caption_minimum": caption_minimum,
        "checks": checks, "passed": all(checks.values()),
        "notes": ["规则筛查不等同人工审片；发布前仍需成人审核。"],
    }
