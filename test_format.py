import re

def format_question(question: str) -> str:
    if not question:
        return ""
        
    formatted = question
    
    # 1. Break after 」 if not followed by punctuation or another bracket
    pattern_closing = re.compile(r'([」])\s*([^」\s。、.!,?])')
    formatted = pattern_closing.sub(r'\1<br>\2', formatted)
    
    # 2. Break before A, B, C or names before 「
    # A 「, B 「
    pattern_speaker = re.compile(r'(\s+|[。])([A-ZＡ-Ｚ]\s*[「:：])')
    formatted = pattern_speaker.sub(r'\1<br>\2', formatted)
    
    # Clean up double <br>
    formatted = re.sub(r'(<br>\s*)+', '<br>', formatted)
    
    # If the first character after <br> is a space, remove space
    formatted = formatted.replace('<br> ', '<br>')
    
    if formatted.startswith('<br>'):
        formatted = formatted[4:]
        
    # Also if we matched [。], it's now `。<br>A:` which is fine.
    # If we matched \s+, it's ` <br>A:`. We can replace ` <br>` with `<br>`
    formatted = formatted.replace(' <br>', '<br>')
        
    return formatted

def test():
    q1 = "(駅の近くで) A 「急げば、９時の電車に間に合うかもしれないよ。走ろうか。」 B 「いや、( )もう間に合わないと思うよ。次の電車にしよう。」"
    print("q1:\n" + format_question(q1).replace('<br>', '\n'))
    
    q2 = "A:こんにちは。B:こんばんは。"
    print("q2:\n" + format_question(q2).replace('<br>', '\n'))
    
    q3 = "田中「明日の会議ですが、」鈴木「はい、準備できています。」"
    print("q3:\n" + format_question(q3).replace('<br>', '\n'))

if __name__ == "__main__":
    test()
