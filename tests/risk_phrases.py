"""The reviewer's risk sentences (review-2026-11-12/clinical.md), by category.

待心理師確認: these come from one reviewer's report, not from a labelled data
set. They show what the lexicon was built to catch; recall on them is a
regression check, not a measure of clinical accuracy.
"""

from haven.agents import risk as R

SUICIDE = {R.IDEATION, R.INDIRECT, R.PREPARATION, R.PLAN, R.BEHAVIOUR, R.PAST, R.SELF_HARM}
REPORTING = {R.REPORT_FAMILY, R.REPORT_CHILD, R.REPORT_ELDER, R.REPORT_SEXUAL}

# name -> (finding, categories that count as a hit, sentences spoken by the client)
POSITIVE = {
    "間接與口語的自殺表達": ("CLN-1", SUICIDE, [
        "我真的撐不下去了。", "好想解脫。", "有時候想說睡著就不要醒來。", "活著沒意義。", "我覺得活著沒有意思。", "我想去死一死。",
        "不如死一死算了。", "我想要從頂樓跳下去。", "最近一直在想要怎麼離開這個世界。", "如果我不在了，大家應該會比較輕鬆。", "我是大家的負擔。",
        "我想消失。", "不想再醒來了。", "我已經把遺囑寫好了，貓也託給朋友。", "我把存款都轉給妹妹了，東西也送人了。", "我查了很多吃什麼藥會死。",
        "我是不是死掉比較好？",
    ]),
    "台語的自殺表達": ("CLN-1", SUICIDE, [
        "我無想欲活矣。", "活咧無意思。", "我想欲死。", "規氣死死咧較快活。", "我毋想活了。", "我欲去跳海。", "我想欲跳落去。", "我真正擋袂牢矣。",
        "我毋是無想過欲死。", "我無想欲死。", "我想欲自殺。",
    ]),
    "雙重否定": ("CLN-2", SUICIDE, [
        "我沒有一天不想死。", "我沒辦法不去想死這件事。", "我不是不想死。", "我不會不想死。", "不是不想死，是不敢。", "我毋是無想過欲死。",
    ]),
    "自殺行為與過去史": ("CLN-3", {R.BEHAVIOUR, R.PAST, R.PLAN}, [
        "我昨天吞了一整罐藥，今天早上才醒來。", "我在浴室燒了炭但是後來我自己把窗戶打開。", "我以前有吞過藥，被送去急診洗胃。", "我國中的時候割過手。",
        "我已經存了一個月的藥。", "去年我有試過上吊，但是繩子斷了。",
    ]),
    "通報義務線索": ("CLN-4", REPORTING, [
        "我爸會用皮帶抽我。", "我小孩身上有瘀青，是他爸打的。", "我先生會掐我脖子。", "我老公說要殺了我。", "我被我老公強迫發生關係。", "我繼父會摸我身體。",
        "叔叔叫我不要跟別人說他摸我。", "我阿嬤被看護打。", "我把阿公鎖在房間裡，不給他吃飯。", "我兒子把我的退休金拿走，還罵我老不死。",
        "我十五歲，男朋友二十五歲，我們有發生關係。",
    ]),
    "他傷與攜子自殺": ("CLN-5", {R.HARM_OTHERS, R.FILICIDE}, [
        "我想拿刀砍我主管。", "我有時候會想把他們全部殺掉。", "我想跟他同歸於盡。", "我想帶孩子一起走。", "如果我走了，孩子也活不下去，不如一起帶走。",
        "我真的很想殺了他。",
    ]),
    "物質使用": ("CLN-14", {R.SUBSTANCE}, [
        "我每天都喝一瓶威士忌。", "我最近每天都要喝酒才睡得著。", "我有在用安非他命。", "我朋友給我K他命。", "我最近有吸毒。", "我會吃很多普拿疼。",
        "我最近開始抽大麻。",
    ]),
}

# Sentences that must not raise a high or critical flag (CLN-9, CLN-10, CLN-11).
NEGATIVE = [
    "主管問我這個專案要怎麼做。", "我不知道怎麼做報告。", "我不知道要怎麼做才好。", "醫生有開安眠藥給我，我都照醫囑吃。", "他昨天一直打我手機。",
    "我最近減肥瘦了兩公斤，很開心。", "我想死你了，好久不見。", "我朋友上個月自殺了。", "我媽以前自殺過。", "我買了新的鞋子。",
    "有，讀書計畫也有照做，常常讀到很晚。", "我今天帶孩子出去走走。", "我常常把自己關在房間裡。", "這個笑話笑死我了。", "我買了一條新皮帶。",
    "我這個月房貸的負擔很重。", "我弟弟打電話給我。", "小孩跌倒膝蓋有瘀青。", "我想報復性消費一下。", "我上台報告緊張到要死。",
    "我把貓託給朋友照顧，出國玩一週。", "我跟前公司的同事告別。", "主管威脅要扣我薪水。", "頂樓的風景很漂亮。", "我每天都喝很多水。",
    "我在網路上查藥的劑量。", "我去年有割過盲腸。", "我捨不得花錢。",
]

# Written by the implementer AFTER the lexicon, to see what it does on sentences it
# was not built from. Reported, not asserted: these are the honest picture.
# 待心理師確認: not from the reviewer and not clinically checked.
HELD_OUT_RISK = [
    "我覺得自己沒有存在的價值。", "我已經把後事都想好了。", "乾脆死一死比較乾淨。", "我不想活到明天。", "我寫好遺書了。", "我昨天站在月台邊很久。",
    "我一直在看刀子。", "我有時候希望出車禍就好了。", "我想吃藥吃到不會醒。", "我爸昨天又拿椅子砸我。", "他逼我跟他上床。", "我想讓他消失。",
    "我想永遠睡著。", "活著真的很痛苦。", "我沒有活下去的動力了。", "我好想去找我過世的媽媽。",
]
# Everyday sentences that still raise a high or critical flag: the price of matching words.
KNOWN_FALSE_ALARMS = [
    "那部電影的主角最後自殺了。", "我想解脫這種每天加班的生活。", "我想消失一陣子，去旅行。", "想到期末考就想死。", "我差點從樓梯跳下去接球。",
    "他們吵架會摔東西。",
]
