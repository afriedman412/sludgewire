from sludgewire23.updater import HousePTRUpdater
from sludgewire23.senate_updater import SenatePTRUpdater

if __name__=="__main__":
    p = HousePTRUpdater()
    p.update_ptrs()

    s = SenatePTRUpdater()
    s.full_search()

