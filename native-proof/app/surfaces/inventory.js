import { surface as bulk } from './BulkSlot';
import { surface as button } from './ButtonSlot';
import { surface as calendar } from './CalendarSlot';
import { surface as dateTime } from './DateTimeSlot';
import { surface as filters } from './FiltersSlot';
import { surface as mediaCard } from './MediaCardSlot';
import { surface as rails } from './RailsSlot';
import { surface as preferences } from './PreferencesSlot';
import { surface as progress } from './ProgressSlot';
import { surface as rating } from './RatingSlot';
import { surface as search } from './SearchSlot';
import { surface as appearanceSettings } from './AppearanceSettingsSlot';
import { surface as cardsSettings } from './CardsSettingsSlot';
import { surface as homeSettings } from './HomeSettingsSlot';
import { surface as settingsCard } from './SettingsCardSlot';
import { surface as providerSettings } from './ProviderSettingsSlot';
import { surface as dataAccessNotifications } from './DataAccessNotificationsSlot';

export const surfaces = [search, mediaCard, rails, filters, rating, progress, dateTime, calendar, bulk, button, settingsCard, providerSettings, preferences, appearanceSettings, cardsSettings, homeSettings, dataAccessNotifications];
