from sludgewire.house_updater import HousePTRUpdater
from sludgewire.senate_updater import SenatePTRUpdater

if __name__=="__main__":
    p = HousePTRUpdater()
    p.update_ptrs()

    s = SenatePTRUpdater()
    s.full_ptr_updater()

