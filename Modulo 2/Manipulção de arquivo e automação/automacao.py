import pyautogui as pg


#pg.moveTo(100, 150, duration=1.5)
#pg.moveTo(100,350, duration=1.5)

pg.press("win")

pg.sleep(1)

pg.write("chrome", interval= 0.5)

pg.press("enter")

pg.write("www.youtube.com")

pg.press('enter')

