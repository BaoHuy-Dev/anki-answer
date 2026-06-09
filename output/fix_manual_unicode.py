from __future__ import annotations

import re

from anki_ocr.anki_connect import AnkiConnectClient
from anki_ocr.core import merge_back_block, merge_front_ocr_block, render_back_block, render_front_ocr_block
from anki_ocr.enrich import AnswerOption


client = AnkiConnectClient()


def update_back(note_id: int, payload: dict) -> None:
    note = client.notes_info([note_id])[0]
    back = note["fields"]["Back"]["value"]
    client.update_note_fields(note_id, {"Back": merge_back_block(back, render_back_block(payload))})
    print("updated back", note_id)


def update_front(note_id: int, block: str) -> None:
    note = client.notes_info([note_id])[0]
    front = note["fields"]["Front"]["value"]
    client.update_note_fields(note_id, {"Front": merge_front_ocr_block(front, block)})
    print("updated front", note_id)


def options(items: list[tuple[str, str, str, str, bool, str]]) -> list[AnswerOption]:
    return [AnswerOption(*item) for item in items]


BUNPOU_FIXES: dict[int, dict] = {
    1780328985807: {
        "answer": "④ 本屋や美容院など",
        "japanese_question": "さくら大学の周りには、レストランや喫茶店などの____ ____ ★ ____ある。",
        "romaji_question": "Sakura daigaku no mawari ni wa, resutoran ya kissaten nado no ____ ____ ★ ____ aru.",
        "vietnamese_question": "Xung quanh Đại học Sakura có ____ ____ ★ ____ như nhà hàng, quán cà phê.",
        "romaji_answer": "honya ya biyouin nado",
        "vietnamese_answer": "hiệu sách, tiệm làm đẹp, v.v.",
        "completed_sentence": "さくら大学の周りには、レストランや喫茶店などの飲食店を中心に、本屋や美容院などいろいろな店がある。",
        "correct_order": "② 飲食店を → ① 中心に → ④ 本屋や美容院など → ③ いろいろな店が",
        "answer_options": options(
            [
                ("①", "中心に", "chuushin ni", "lấy ... làm trung tâm", False, "Đi với 「Nを」 trong mẫu 「Nを中心に」."),
                ("②", "飲食店を", "inshokuten o", "các hàng/quán ăn uống", False, "Tân ngữ của 「中心に」."),
                ("③", "いろいろな店が", "iroiro na mise ga", "nhiều cửa hàng khác nhau", False, "Chủ ngữ đứng trước 「ある」."),
                ("④", "本屋や美容院など", "honya ya biyouin nado", "hiệu sách, tiệm làm đẹp, v.v.", True, "Mảnh nằm ở vị trí ★."),
            ]
        ),
        "grammar_note": "Mẫu 「Nを中心に」 nghĩa là “lấy N làm trung tâm/chủ yếu”. Câu liệt kê các cửa hàng quanh trường, chủ yếu là hàng ăn uống, thêm hiệu sách/tiệm làm đẹp.",
    },
    1780328967681: {
        "answer": "② のは",
        "japanese_question": "今の会社に就職したときに、北町で一人暮らしを始めた。会社から遠い____ ____ ★ ____からだ。",
        "romaji_question": "Ima no kaisha ni shuushoku shita toki ni, Kitamachi de hitorigurashi o hajimeta. Kaisha kara tooi ____ ____ ★ ____ kara da.",
        "vietnamese_question": "Khi vào công ty hiện tại, tôi bắt đầu sống một mình ở Kitamachi. Lý do là vì ____ ____ ★ ____ dù xa công ty.",
        "romaji_answer": "no wa",
        "vietnamese_answer": "việc/lý do là...",
        "completed_sentence": "今の会社に就職したときに、北町で一人暮らしを始めた。会社から遠いのに北町を選んだのは、ずっと北町に住んでみたかったからだ。",
        "correct_order": "④ のに → ① 北町を選んだ → ② のは → ③ ずっと北町に住んでみたかった",
        "answer_options": options(
            [
                ("①", "北町を選んだ", "Kitamachi o eranda", "đã chọn Kitamachi", False, "Hành động được giải thích lý do."),
                ("②", "のは", "no wa", "việc/lý do là", True, "Mảnh ở vị trí ★, mở phần giải thích lý do."),
                ("③", "ずっと北町に住んでみたかった", "zutto Kitamachi ni sunde mitakatta", "đã luôn muốn thử sống ở Kitamachi", False, "Lý do đứng trước 「からだ」."),
                ("④", "のに", "no ni", "mặc dù", False, "Nối với 「会社から遠い」 để tạo nghĩa nhượng bộ."),
            ]
        ),
        "grammar_note": "Mẫu chính là 「AのにBのはCからだ」: dù A nhưng chọn B là vì C.",
    },
    1780329087624: {
        "answer": "① コースなので",
        "japanese_question": "このパソコン教室には様々なコースがあります。基礎コースは、パソコンの____ ____ ★ ____ぴったりです。",
        "romaji_question": "Kono pasokon kyoushitsu ni wa samazama na koosu ga arimasu. Kiso koosu wa, pasokon no ____ ____ ★ ____ pittari desu.",
        "vietnamese_question": "Lớp máy tính này có nhiều khóa học. Khóa cơ bản thì ____ ____ ★ ____ rất phù hợp.",
        "romaji_answer": "koosu na node",
        "vietnamese_answer": "vì là khóa học...",
        "completed_sentence": "このパソコン教室には様々なコースがあります。基礎コースは、パソコンの基本的な使い方になれるためのコースなので、初めて習う方にぴったりです。",
        "correct_order": "④ 基本的な使い方に → ③ なれるための → ① コースなので → ② 初めて習う方に",
        "answer_options": options(
            [
                ("①", "コースなので", "koosu na node", "vì là khóa học", True, "Mảnh ở vị trí ★, nối lý do với phần sau."),
                ("②", "初めて習う方に", "hajimete narau kata ni", "đối với người học lần đầu", False, "Đứng trước 「ぴったり」."),
                ("③", "なれるための", "nareru tame no", "để làm quen với", False, "Bổ nghĩa cho 「コース」."),
                ("④", "基本的な使い方に", "kihonteki na tsukaikata ni", "với cách dùng cơ bản", False, "Đi với 「なれる」."),
            ]
        ),
        "grammar_note": "Cụm 「基本的な使い方に慣れるためのコース」 nghĩa là khóa học để làm quen với cách dùng cơ bản.",
    },
    1780328865187: {
        "answer": "④ 思う",
        "japanese_question": "私は今住んでいるアパートは線路の近くにある。住み始めたころは、電車の通る____ ____ ★ ____が、すぐ気にならなくなった。",
        "romaji_question": "Watashi wa ima sunde iru apaato wa senro no chikaku ni aru. Sumi hajimeta koro wa, densha no tooru ____ ____ ★ ____ ga, sugu ki ni naranaku natta.",
        "vietnamese_question": "Căn hộ tôi đang ở gần đường ray. Lúc mới ở, ____ ____ ★ ____, nhưng rồi nhanh chóng không còn bận tâm.",
        "romaji_answer": "omou",
        "vietnamese_answer": "nghĩ/cảm thấy",
        "completed_sentence": "私は今住んでいるアパートは線路の近くにある。住み始めたころは、電車の通る音がしてうるさいと思うこともあったが、すぐ気にならなくなった。",
        "correct_order": "③ 音がして → ① うるさいと → ④ 思う → ② こともあった",
        "answer_options": options(
            [
                ("①", "うるさいと", "urusai to", "rằng ồn", False, "Nối với 「思う」."),
                ("②", "こともあった", "koto mo atta", "cũng có lúc", False, "Kết thúc cụm trải nghiệm trong quá khứ."),
                ("③", "音がして", "oto ga shite", "có tiếng/âm thanh", False, "Mô tả nguyên nhân thấy ồn."),
                ("④", "思う", "omou", "nghĩ/cảm thấy", True, "Mảnh ở vị trí ★."),
            ]
        ),
        "grammar_note": "Cụm 「うるさいと思うこともあった」 nghĩa là “cũng có lúc tôi thấy ồn”.",
    },
    1780328880831: {
        "answer": "② している",
        "japanese_question": "母は「風邪をひかないのは、____ ____ ★ ____。」とよく言っている。",
        "romaji_question": "Haha wa “kaze o hikanai no wa, ____ ____ ★ ____.” to yoku itte iru.",
        "vietnamese_question": "Mẹ thường nói: “Sở dĩ không bị cảm là nhờ ____ ____ ★ ____.”",
        "romaji_answer": "shite iru",
        "vietnamese_answer": "đang/ thường làm",
        "completed_sentence": "母は「風邪をひかないのは、毎朝ジョギングをしているおかげだ。」とよく言っている。",
        "correct_order": "④ 毎朝 → ① ジョギングを → ② している → ③ おかげだ",
        "answer_options": options(
            [
                ("①", "ジョギングを", "jogingu o", "chạy bộ", False, "Tân ngữ của 「している」."),
                ("②", "している", "shite iru", "đang/thường làm", True, "Mảnh ở vị trí ★."),
                ("③", "おかげだ", "okage da", "là nhờ", False, "Nêu nguyên nhân tích cực."),
                ("④", "毎朝", "maiasa", "mỗi sáng", False, "Trạng từ thời gian."),
            ]
        ),
        "grammar_note": "Mẫu 「Nのおかげだ」 nêu nguyên nhân tích cực: không bị cảm là nhờ chạy bộ mỗi sáng.",
    },
    1780328881365: {
        "answer": "① の",
        "japanese_question": "A「今度のさよならパーティーで、みんなで歌う歌は、これでいいですか。」 B「すみません。この歌は好きなんですが、少しむずかしいです____ ____ ★ ____してほしいです。」",
        "romaji_question": "A: Kondo no sayonara paatii de, minna de utau uta wa, kore de ii desu ka. B: Sumimasen. Kono uta wa suki nan desu ga, sukoshi muzukashii desu ____ ____ ★ ____ shite hoshii desu.",
        "vietnamese_question": "A: Bài hát mọi người hát ở tiệc chia tay lần này chọn bài này được không? B: Xin lỗi, tôi thích bài này nhưng hơi khó, nên muốn ____ ____ ★ ____.",
        "romaji_answer": "no",
        "vietnamese_answer": "cái/bài",
        "completed_sentence": "A「今度のさよならパーティーで、みんなで歌う歌は、これでいいですか。」 B「すみません。この歌は好きなんですが、少しむずかしいですから、ほかのにしてほしいです。」",
        "correct_order": "④ から → ② ほか → ① の → ③ に",
        "answer_options": options(
            [
                ("①", "の", "no", "cái/bài", True, "Mảnh ở vị trí ★ trong 「ほかのにする」."),
                ("②", "ほか", "hoka", "khác", False, "Ghép với 「の」 thành 「ほかの」."),
                ("③", "に", "ni", "thành/chọn làm", False, "Đi với 「する」 trong 「ほかのにする」."),
                ("④", "から", "kara", "vì", False, "Nêu lý do: vì bài này hơi khó."),
            ]
        ),
        "grammar_note": "Cụm 「ほかのにしてほしい」 nghĩa là “muốn đổi sang bài/cái khác”.",
    },
    1780328881897: {
        "answer": "③ やらせて",
        "japanese_question": "最近、子どもがピアノを習いたいと言いだした。わたしは、子どもが____ ____ ★ ____と思っている。",
        "romaji_question": "Saikin, kodomo ga piano o naraitai to iidashita. Watashi wa, kodomo ga ____ ____ ★ ____ to omotte iru.",
        "vietnamese_question": "Gần đây con tôi nói muốn học piano. Tôi nghĩ rằng ____ ____ ★ ____.",
        "romaji_answer": "yarasete",
        "vietnamese_answer": "để cho làm",
        "completed_sentence": "最近、子どもがピアノを習いたいと言いだした。わたしは、子どもがしたいと思うことはやらせてやりたいと思っている。",
        "correct_order": "① したい → ④ と思うことは → ③ やらせて → ② やりたい",
        "answer_options": options(
            [
                ("①", "したい", "shitai", "muốn làm", False, "Đi với 「子どもが」."),
                ("②", "やりたい", "yaritai", "muốn làm/cho làm", False, "Kết thúc cụm 「やらせてやりたい」."),
                ("③", "やらせて", "yarasete", "để cho làm", True, "Mảnh ở vị trí ★."),
                ("④", "と思うことは", "to omou koto wa", "những điều mà (con) nghĩ là muốn...", False, "Biến phần trước thành chủ đề."),
            ]
        ),
        "grammar_note": "「やらせてやりたい」 nghĩa là muốn để/cho con làm điều con muốn.",
    },
    1780328882968: {
        "answer": "① すこし",
        "japanese_question": "田中先生の研究室で) 学生「田中先生はいらっしゃいますか。」 秘書「今、ほかの学生と話して____ ____ ★ ____ください。」",
        "romaji_question": "Tanaka sensei no kenkyuushitsu de. Gakusei: Tanaka sensei wa irasshaimasu ka. Hisho: Ima, hoka no gakusei to hanashite ____ ____ ★ ____ kudasai.",
        "vietnamese_question": "Ở phòng nghiên cứu của thầy Tanaka. Sinh viên: Thầy Tanaka có ở đây không? Thư ký: Hiện thầy đang nói chuyện với sinh viên khác, nên xin ____ ____ ★ ____.",
        "romaji_answer": "sukoshi",
        "vietnamese_answer": "một chút",
        "completed_sentence": "田中先生の研究室で) 学生「田中先生はいらっしゃいますか。」 秘書「今、ほかの学生と話していらっしゃいますから、すこし待ってください。」",
        "correct_order": "④ いらっしゃいます → ② から → ① すこし → ③ 待って",
        "answer_options": options(
            [
                ("①", "すこし", "sukoshi", "một chút", True, "Mảnh ở vị trí ★."),
                ("②", "から", "kara", "vì/nên", False, "Nêu lý do."),
                ("③", "待って", "matte", "đợi", False, "Đi với 「ください」."),
                ("④", "いらっしゃいます", "irasshaimasu", "đang/có mặt (kính ngữ)", False, "Kính ngữ của 「いる」."),
            ]
        ),
        "grammar_note": "「話していらっしゃいます」 là kính ngữ của 「話している」; sau đó dùng 「から」 để giải thích lý do phải đợi.",
    },
    1780328883500: {
        "answer": "① 意味だった",
        "japanese_question": "ジョン「この『りかい』という言葉はどういう意味ですか。」 アリ「ああ、確か『わかる』____ ____ ★ ____ んですけど。」",
        "romaji_question": "Jon: Kono 'rikai' to iu kotoba wa dou iu imi desu ka. Ari: Aa, tashika 'wakaru' ____ ____ ★ ____ n desu kedo.",
        "vietnamese_question": "John: Từ “理解” này nghĩa là gì? Ali: À, hình như là ____ ____ ★ ____ “hiểu”.",
        "romaji_answer": "imi datta",
        "vietnamese_answer": "là nghĩa",
        "completed_sentence": "ジョン「この『りかい』という言葉はどういう意味ですか。」 アリ「ああ、確か『わかる』というような意味だったと思うんですけど。」",
        "correct_order": "② という → ④ ような → ① 意味だった → ③ と思う",
        "answer_options": options(
            [
                ("①", "意味だった", "imi datta", "là nghĩa", True, "Mảnh ở vị trí ★."),
                ("②", "という", "to iu", "gọi là/rằng", False, "Nối với từ được giải thích."),
                ("③", "と思う", "to omou", "tôi nghĩ", False, "Diễn đạt phỏng đoán."),
                ("④", "ような", "you na", "kiểu như", False, "Làm mềm cách giải thích."),
            ]
        ),
        "grammar_note": "Cụm 「『わかる』というような意味だったと思う」 nghĩa là “tôi nghĩ nó có nghĩa kiểu như ‘hiểu’”.",
    },
}


for note_id, payload in BUNPOU_FIXES.items():
    update_back(note_id, payload)

update_front(
    1780567175829,
    render_front_ocr_block("これはらくな仕事ではない。", ["① 安全な", "② 危険な", "③ 簡単な", "④ 大変な"]),
)

update_front(
    1780328985807,
    render_front_ocr_block(
        "さくら大学の周りには、レストランや喫茶店などの____ ____ ★ ____ある。",
        ["① 中心に", "② 飲食店を", "③ いろいろな店が", "④ 本屋や美容院など"],
    ),
)
