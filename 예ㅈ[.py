age = input( "현재 나이" )
print("현재나이", age)
print("할인률", 0.3)
price = input( "원가" )
print("원가", price)
if age <= 15:
  sale = (price * 0.3)
  print("할인가", sale)
else:
  print("할인받을 수 있는 나이가 아닙니다.\n", price)
