import logging
from datetime import timedelta
from aiohttp import ClientSession
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.helpers.device_registry import DeviceEntryType

from .const import (
    DOMAIN,
    URL_LOGIN,
    HEADERS_LOGIN,
    HEADERS_POST,
    URL_HOME,
    URL_INDEX,
    URL_RECEIPTS,
    URL_LISTA_LUNI,
)

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(minutes=5)

class EBlocDataUpdateCoordinator(DataUpdateCoordinator):
    """Coordonator pentru actualizarea datelor în integrarea E-bloc."""

    def __init__(self, hass, config):
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )
        self.config = config
        self.session = None
        self.authenticated = False
    
    def _get_luna_activa(self, lista_luni):
        """Get active month from the months list."""
        first_three_months = {k: lista_luni[k] for k in list(lista_luni.keys())[:3]}     
        return next((v['luna'] for k, v in first_three_months.items() if v['open'] == '0'), None) or list(first_three_months.values())[0]['luna']
    
    async def _async_update_data(self):
        """Fetch data from API."""
        try:
            if not self.session:
                self.session = ClientSession()
            if not self.authenticated:
                await self._authenticate()

            initial_payload = {"pIdAsoc": self.config["pIdAsoc"], "pIdAp": self.config["pIdAp"]}
            lista_luni = await self._fetch_data(URL_LISTA_LUNI, initial_payload)
            luna_activa = self._get_luna_activa(lista_luni)

            payload = {
                "pIdAsoc": self.config["pIdAsoc"],
                "pIdAp": self.config["pIdAp"],
                "pLuna": luna_activa
            }

            return {
                "home": await self._fetch_data(URL_HOME, payload),
                "index": await self._fetch_data(URL_INDEX, payload),
                "receipts": await self._fetch_data(URL_RECEIPTS, payload),
                "lista_luni": lista_luni,
                "luna_activa": luna_activa
            }
        except Exception as e:
            raise UpdateFailed(f"Eroare la actualizarea datelor: {e}")

    async def _authenticate(self):
        """Authenticate with API."""
        payload = {"pUser": self.config["pUser"], "pPass": self.config["pPass"]}
        try:
            async with self.session.post(URL_LOGIN, data=payload, headers=HEADERS_LOGIN) as response:
                if response.status == 200 and "Acces online proprietari" in await response.text():
                    self.authenticated = True
                else:
                    raise UpdateFailed("Autentificare eșuată.")
        except Exception as e:
            raise UpdateFailed(f"Eroare la autentificare: {e}")

    async def _fetch_data(self, url, payload):
        """Make API request and return JSON."""
        try:
            async with self.session.post(url, data=payload, headers=HEADERS_POST) as response:
                return await response.json() if response.status == 200 else {}
        except Exception as e:
            _LOGGER.error("Eroare la conexiunea cu serverul: %s", e)
            return {}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities):
    """Set up sensors from a config entry."""
    coordinator = EBlocDataUpdateCoordinator(hass, entry.data)
    await coordinator.async_config_entry_first_refresh()

    sensors = [
        ClientSensor(coordinator),
        ApaReceSensor(coordinator),
        ApaCaldaSensor(coordinator),
        CalduraSensor(coordinator),
        CurentSensor(coordinator),
        PlatiSensor(coordinator),
        ApartamentSensor(coordinator),
        PersoaneSensor(coordinator),
        RestantaSensor(coordinator),
        UltimaZiSensor(coordinator),
        ContorTrimisSensor(coordinator),
        IncepereCitireSensor(coordinator),
        IncheiereCitireSensor(coordinator),
        LunaVecheSensor(coordinator),
        LunaCurentaSensor(coordinator),
        NivelRestantaSensor(coordinator),
    ]
    async_add_entities(sensors)

class EBlocSensorBase(SensorEntity):
    """Base sensor class with common functionality."""

    def __init__(self, coordinator):
        """Initialize the sensor."""
        self._coordinator = coordinator
        self._attr_should_poll = False

    @property
    def available(self):
        """Return if entity is available."""
        return self._coordinator.last_update_success

    @property
    def device_info(self):
        """Return device info."""
        return {
            "identifiers": {(DOMAIN, "e-bloc")},
            "name": "E-bloc.ro",
            "manufacturer": "E-bloc.ro",
            "entry_type": DeviceEntryType.SERVICE,
        }

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

    async def async_update(self):
        """Update the entity."""
        await self._coordinator.async_request_refresh()

class ClientSensor(EBlocSensorBase):
    """Sensor for client information."""

    _attr_name = "Date client"
    _attr_unique_id = f"{DOMAIN}_client"
    _attr_icon = "mdi:account-details"

    @property
    def native_value(self):
        """Return client code."""
        return self._coordinator.data.get("home", {}).get("1", {}).get("cod_client")

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        data = self._coordinator.data.get("home", {}).get("1", {})
        return {
            "Apartament": data.get("ap"),
            "Persoane": data.get("nr_pers_afisat"),
            "Restanță": f"{int(data.get('datorie', 0)) / 100:.2f} RON",
            "Ultima zi plată": data.get("ultima_zi_plata"),
            "Contor trimis": "Da" if data.get("contoare_citite") == "1" else "Nu",
            "Perioadă citire": f"{data.get('citire_contoare_start', '')} - {data.get('citire_contoare_end', '')}",
            "Luna veche": data.get("luna_veche"),
            "Nivel restanță": data.get("nivel_restanta")
        }

class ApaReceSensor(EBlocSensorBase):
    """Sensor for cold water."""

    _attr_name = "Apă rece"
    _attr_unique_id = f"{DOMAIN}_apa_rece"
    _attr_icon = "mdi:water-pump"
    _attr_native_unit_of_measurement = "m³"

    @property
    def native_value(self):
        """Return current value."""
        data = self._coordinator.data.get("index", {}).get("2", {})
        try:
            return round(float(data.get("index_nou", 0)) / 1000, 3)
        except (ValueError, TypeError):
            return None

class ApaCaldaSensor(EBlocSensorBase):
    """Sensor for hot water."""

    _attr_name = "Apă caldă"
    _attr_unique_id = f"{DOMAIN}_apa_calda"
    _attr_icon = "mdi:water-thermometer"
    _attr_native_unit_of_measurement = "m³"

    @property
    def native_value(self):
        """Return current value."""
        data = self._coordinator.data.get("index", {}).get("3", {})
        try:
            return round(float(data.get("index_nou", 0)) / 1000, 3)
        except (ValueError, TypeError):
            return None

class CalduraSensor(EBlocSensorBase):
    """Sensor for heating."""

    _attr_name = "Căldură"
    _attr_unique_id = f"{DOMAIN}_caldura"
    _attr_icon = "mdi:radiator"
    _attr_native_unit_of_measurement = "kWh"

    @property
    def native_value(self):
        """Return current value."""
        data = self._coordinator.data.get("index", {}).get("4", {})
        try:
            return round(float(data.get("index_nou", 0)) / 1000, 3)
        except (ValueError, TypeError):
            return None

class CurentSensor(EBlocSensorBase):
    """Sensor for electricity."""

    _attr_name = "Curent"
    _attr_unique_id = f"{DOMAIN}_curent"
    _attr_icon = "mdi:flash"
    _attr_native_unit_of_measurement = "kWh"

    @property
    def native_value(self):
        """Return current value."""
        data = self._coordinator.data.get("index", {}).get("5", {})
        try:
            return round(float(data.get("index_nou", 0)) / 1000, 3)
        except (ValueError, TypeError):
            return None

class PlatiSensor(EBlocSensorBase):
    """Sensor for payments."""

    _attr_name = "Plăți"
    _attr_unique_id = f"{DOMAIN}_plati"
    _attr_icon = "mdi:receipt"

    @property
    def native_value(self):
        """Return number of receipts."""
        receipts = self._coordinator.data.get("receipts", {})
        return len(receipts) if isinstance(receipts, dict) else 0

    @property
    def extra_state_attributes(self):
        """Return receipts details."""
        receipts = self._coordinator.data.get("receipts", {})
        if not isinstance(receipts, dict):
            return {}
            
        return {
            f"Chitanța {i}": f"{r.get('numar', '')} - {r.get('data', '')} - {int(r.get('suma', 0))/100:.2f} RON"
            for i, r in enumerate(receipts.values(), 1)
        }

# Simple attribute sensors
class ApartamentSensor(EBlocSensorBase):
    _attr_name = "Apartament"
    _attr_unique_id = f"{DOMAIN}_apartament"
    _attr_icon = "mdi:home"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("ap")

class PersoaneSensor(EBlocSensorBase):
    _attr_name = "Persoane"
    _attr_unique_id = f"{DOMAIN}_persoane"
    _attr_icon = "mdi:account-multiple"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("nr_pers_afisat")

class RestantaSensor(EBlocSensorBase):
    _attr_name = "Restanță"
    _attr_unique_id = f"{DOMAIN}_restanta"
    _attr_icon = "mdi:cash-remove"
    _attr_native_unit_of_measurement = "RON"

    @property
    def native_value(self):
        datorie = self._coordinator.data.get("home", {}).get("1", {}).get("datorie")
        return round(int(datorie)/100, 2) if datorie else 0.00

class UltimaZiSensor(EBlocSensorBase):
    _attr_name = "Ultima zi plată"
    _attr_unique_id = f"{DOMAIN}_ultima_zi"
    _attr_icon = "mdi:calendar-clock"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("ultima_zi_plata")

class ContorTrimisSensor(EBlocSensorBase):
    _attr_name = "Contor trimis"
    _attr_unique_id = f"{DOMAIN}_contor_trimis"
    _attr_icon = "mdi:send-check"

    @property
    def native_value(self):
        val = self._coordinator.data.get("home", {}).get("1", {}).get("contoare_citite")
        return "Da" if val == "1" else "Nu"

class IncepereCitireSensor(EBlocSensorBase):
    _attr_name = "Începere citire"
    _attr_unique_id = f"{DOMAIN}_citire_start"
    _attr_icon = "mdi:calendar-start"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("citire_contoare_start")

class IncheiereCitireSensor(EBlocSensorBase):
    _attr_name = "Încheiere citire"
    _attr_unique_id = f"{DOMAIN}_citire_end"
    _attr_icon = "mdi:calendar-end"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("citire_contoare_end")

class LunaVecheSensor(EBlocSensorBase):
    _attr_name = "Luna veche"
    _attr_unique_id = f"{DOMAIN}_luna_veche"
    _attr_icon = "mdi:calendar-alert"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("luna_veche")

class LunaCurentaSensor(EBlocSensorBase):
    _attr_name = "Luna curentă"
    _attr_unique_id = f"{DOMAIN}_luna_curenta"
    _attr_icon = "mdi:calendar-month"

    @property
    def native_value(self):
        return self._coordinator.data.get("luna_activa")

class NivelRestantaSensor(EBlocSensorBase):
    _attr_name = "Nivel restanță"
    _attr_unique_id = f"{DOMAIN}_nivel_restanta"
    _attr_icon = "mdi:alert-circle"

    @property
    def native_value(self):
        return self._coordinator.data.get("home", {}).get("1", {}).get("nivel_restanta")