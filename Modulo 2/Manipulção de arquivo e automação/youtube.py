import pyautogui as pg

#pg.mouseInfo()

pg.press('win')

pg.sleep(1)

pg.write('chrome')

pg.press('enter')

pg.sleep(1)

pg.write('www.youtube.com', interval=0.1)

pg.press('enter')

pg.sleep(8)

pg.moveTo(797, 112, duration=1)

pg.sleep(2)

pg.click()

pg.sleep(1)

pg.write('2pac', interval=0.1)

pg.sleep(1)

pg.press('enter')

pg.sleep(4)

pg.move(100, 400, duration=1)

pg.sleep(4)

pg.click()