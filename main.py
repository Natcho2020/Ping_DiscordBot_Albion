import discord
from discord.ext import commands
import os
import json
import re
from datetime import datetime
from threading import Thread
from flask import Flask

# Mini servidor web para Render Free
app_flask = Flask(__name__)
PINGS_DB_PATH = "pings.json"

@app_flask.route('/')
def home():
    return "Bot Albion Online - ONLINE"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)

intents = discord.Intents.default()
intents.message_content = True

actividades = [
    "Dorados",
    "Roaming",
    "Buffo-Ava",
    "Arenas",
    "Gankeo",
    "Estatica",
    "Masmorra Grupal",
]
ping_data = {}
pings_db = {}

def load_pings():
    try:
        with open(PINGS_DB_PATH, "r", encoding="utf-8") as file:
            stored_pings = json.load(file)
    except FileNotFoundError:
        return {}
    if not isinstance(stored_pings, dict):
        raise ValueError("El archivo de pings debe contener un objeto JSON.")
    for message_id, ping in stored_pings.items():
        if not isinstance(ping, dict) or not isinstance(ping.get("roles"), list):
            raise ValueError(f"Registro de ping inválido para el mensaje {message_id}.")
        registrations = ping.setdefault("registrations", {})
        try:
            int(message_id)
            int(ping["guild_id"])
            int(ping["channel_id"])
            int(ping["thread_id"])
            if not all(isinstance(role, str) for role in ping["roles"]):
                raise TypeError("Los roles del ping deben ser texto.")
            if not isinstance(registrations, dict):
                raise TypeError("Las inscripciones deben ser un objeto.")
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Registro de ping inválido para el mensaje {message_id}.") from error
    return stored_pings

def save_pings():
    temporary_path = f"{PINGS_DB_PATH}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as file:
        json.dump(pings_db, file, ensure_ascii=False, indent=2)
    os.replace(temporary_path, PINGS_DB_PATH)

def role_capacity(ping, role_name):
    return ping.get("roles", []).count(role_name)

def number_role_slots(roles):
    totals = {}
    for role_name in roles:
        totals[role_name] = totals.get(role_name, 0) + 1
    occurrences = {}
    numbered_roles = []
    for role_name in roles:
        occurrences[role_name] = occurrences.get(role_name, 0) + 1
        if totals[role_name] > 1:
            numbered_roles.append(f"{role_name} {occurrences[role_name]}")
        else:
            numbered_roles.append(role_name)
    return numbered_roles

def role_registration_count(ping, role_name):
    return sum(registered_role == role_name for registered_role in ping.get("registrations", {}).values())

class AlbionBot(commands.Bot):
    async def setup_hook(self):
        stored_pings = load_pings()
        pings_db.update(stored_pings)
        for message_id, ping in stored_pings.items():
            view = InscripcionView(ping["roles"], int(message_id), int(ping["thread_id"]))
            self.add_view(view, message_id=int(message_id))
        # ESTO ES LO QUE TE FALTABA: registrar el panel principal para que nunca muera
        self.add_view(MainView())
        print(f"Vistas de inscripción restauradas: {len(stored_pings)}")
        print("MainView persistente registrado")
        
bot = AlbionBot(command_prefix="!", intents=intents) # <-- ESTA LINEA TE FALTABA

class InscripcionView(discord.ui.View):
    def __init__(self, roles, message_id, thread_id):
        super().__init__(timeout=None)
        for index, role_name in enumerate(roles):
            self.add_item(InscripcionButton(role_name, message_id, thread_id, index))

class InscripcionButton(discord.ui.Button):
    def __init__(self, role_name, message_id, thread_id, index):
        super().__init__(label=f"Apuntarme: {role_name}", style=discord.ButtonStyle.secondary, custom_id=f"signup_{message_id}_{index}")
        self.role_name = role_name
        self.message_id = message_id
        self.thread_id = thread_id
    async def callback(self, interaction: discord.Interaction):
        ping = pings_db.get(str(self.message_id))
        if ping is None:
            await interaction.response.send_message("Este ping ya no está disponible.", ephemeral=True)
            return
        registrations = ping.setdefault("registrations", {})
        user_id = str(interaction.user.id)
        if user_id in registrations:
            await interaction.response.send_message(f"Ya estás apuntado como {registrations[user_id]}.", ephemeral=True)
            return
        if role_registration_count(ping, self.role_name) >= role_capacity(ping, self.role_name):
            await interaction.response.send_message(f"Ya no quedan plazas para {self.role_name}.", ephemeral=True)
            return
        registrations[user_id] = self.role_name
        save_pings()
        await interaction.response.defer(ephemeral=True)
        try:
            thread = bot.get_channel(self.thread_id) or await bot.fetch_channel(self.thread_id)
            await thread.send(f"{interaction.user.mention} se apuntó como {self.role_name} ✅")
        except discord.HTTPException:
            registrations.pop(user_id, None)
            save_pings()
            await interaction.followup.send("No pude completar tu inscripción.", ephemeral=True)
            return
        await interaction.followup.send(f"Te apuntaste como {self.role_name}.", ephemeral=True)
class WeaponModal(discord.ui.Modal, title="Arma para este rol"):
    arma = discord.ui.TextInput(
        label="¿Qué arma?",
        placeholder="Ej: Camlann, Bloodletter",
        max_length=30,
    )

    def __init__(self, user_id, rol):
        super().__init__()
        self.user_id = user_id
        self.rol = rol

    async def on_submit(self, interaction):
        data = ping_data[self.user_id]
        data["roles"].append(self.rol)
        data["weapons"].append(str(self.arma))
        await interaction.response.edit_message(
            embed=build_roles_embed(self.user_id),
            view=RolesView(self.user_id),
        )


def build_roles_embed(user_id):
    data = ping_data[user_id]
    role_slots = number_role_slots(data["roles"])
    slots = ""
    for i in range(data["cupos"]):
        if i < len(data["roles"]):
            role = data["roles"][i]
            role_slot = role_slots[i]
            weapon = data["weapons"][i]
            icons = {
                "Tanque": "🛡️",
                "Healer": "💚",
                "Dps": "⚔️",
                "Soporte": "🔮",
            }
            slots += f"{icons[role]} `{role_slot}: {weapon}`\n"
        else:
            slots += f"⬜ Slot {i + 1} Vacío\n"
    return discord.Embed(
        title=f"👥 {data['actividad']} {len(data['roles'])}/{data['cupos']}",
        description=slots,
        color=0xD4A44A,
    )


class RolesView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(label="🛡️ Tanque", style=discord.ButtonStyle.secondary)
    async def tanque(self, interaction, button):
        await interaction.response.send_modal(WeaponModal(self.user_id, "Tanque"))

    @discord.ui.button(label="💚 Healer", style=discord.ButtonStyle.secondary)
    async def healer(self, interaction, button):
        await interaction.response.send_modal(WeaponModal(self.user_id, "Healer"))

    @discord.ui.button(label="⚔️ Dps", style=discord.ButtonStyle.secondary)
    async def dps(self, interaction, button):
        await interaction.response.send_modal(WeaponModal(self.user_id, "Dps"))

    @discord.ui.button(label="🔮 Soporte", style=discord.ButtonStyle.secondary)
    async def soporte(self, interaction, button):
        await interaction.response.send_modal(WeaponModal(self.user_id, "Soporte"))

    @discord.ui.button(label="Siguiente →", style=discord.ButtonStyle.success, row=1)
    async def siguiente(self, interaction, button):
        data = ping_data[self.user_id]
        if len(data["roles"]) != data["cupos"]:
            await interaction.response.send_message(
                f"Llena {data['cupos']} slots",
                ephemeral=True,
            )
            return
        await interaction.response.edit_message(
            embed=discord.Embed(
                title="💬 Elige sala y escribe comentario",
                description="Elige donde se enviará el @everyone",
                color=0xD4A44A,
            ),
            view=CanalView(self.user_id, interaction.guild),
        )


class ComentarioModal(discord.ui.Modal, title="Comentario final"):
    coment = discord.ui.TextInput(
        label="Comentario",
        required=False,
        style=discord.TextStyle.long,
        placeholder="Ej: IP 1400+, salimos de Martlock",
    )

    def __init__(self, user_id):
        super().__init__()
        self.user_id = user_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = ping_data[self.user_id]
        data["comentario"] = str(self.coment) or "Sin comentario"
        signup_roles = number_role_slots(data["roles"])
        guild = interaction.guild
        target = (
            discord.utils.get(guild.text_channels, name=data["canal_id"])
            or interaction.channel
        )
        composition = "\n".join(
            f"`{role_slot}: {weapon}`"
            for role_slot, weapon in zip(signup_roles, data["weapons"])
        )
        embed = discord.Embed(
            title=(
                f"⚔️ {data['actividad'].upper()} - "
                f"{data['fecha']} {data['hora']} UTC"
            ),
            description=(
                f"**Compo ({len(data['roles'])}/{data['cupos']})**\n"
                f"{composition}\n\n**Nota:** {data['comentario']}"
            ),
            color=0xD4A44A,
        )
        embed.set_footer(text=f"Creador: {interaction.user.display_name}")

        message = await target.send(content="@everyone", embed=embed)
        thread = await message.create_thread(
            name=f"Inscripciones {data['actividad']} {data['fecha']}"[:100],
            auto_archive_duration=60,
        )
        ping = {
            "guild_id": interaction.guild_id,
            "channel_id": target.id,
            "thread_id": thread.id,
            "roles": signup_roles,
            "registrations": {},
        }
        pings_db[str(message.id)] = ping
        save_pings()

        view = InscripcionView(ping["roles"], message.id, thread.id)
        await message.edit(view=view)
        bot.add_view(view, message_id=message.id)
        await thread.send(
            "Hilo de inscripción creado. Pulsa el botón de tu rol en el ping "
            "para apuntarte."
        )
        await interaction.followup.send(
            f"✅ Ping enviado en {target.mention}",
            ephemeral=True,
        )


class CanalSelect(discord.ui.Select):
    def __init__(self, user_id, guild):
        self.user_id = user_id
        canales = [
            channel
            for channel in guild.text_channels
            if channel.permissions_for(guild.me).send_messages
        ][:25]
        if not canales:
            canales = guild.text_channels[:25]

        options = [
            discord.SelectOption(
                label=f"#{channel.name}",
                value=channel.name,
                description=(
                    f"{len(channel.members)} viendo"
                    if hasattr(channel, "members")
                    else ""
                ),
            )
            for channel in canales
        ]
        super().__init__(
            placeholder="1. Elige la sala donde se enviará...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        ping_data[self.user_id]["canal_id"] = self.values[0]
        await interaction.response.send_message(
            f"Canal: #{self.values[0]} seleccionado. Ahora finaliza:",
            view=ComentarioButtonView(self.user_id),
            ephemeral=True,
        )


class ComentarioButtonView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id

    @discord.ui.button(
        label="💬 Escribir Comentario y Enviar",
        style=discord.ButtonStyle.success,
    )
    async def escribir(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        await interaction.response.send_modal(ComentarioModal(self.user_id))


class CanalView(discord.ui.View):
    def __init__(self, user_id, guild):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.add_item(CanalSelect(user_id, guild))


class FechaCorreccionView(discord.ui.View):
    def __init__(self, user_id, actividad, defaults):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.actividad = actividad
        self.defaults = dict(defaults)

    @discord.ui.button(
        label="Corregir datos",
        style=discord.ButtonStyle.primary,
    )
    async def corregir(self, interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Solo quien inició este ping puede corregir sus datos.",
                ephemeral=True,
            )
            return
        await interaction.response.send_modal(
            FechaModal(
                self.user_id,
                self.actividad,
                defaults=self.defaults,
            )
        )


class FechaModal(discord.ui.Modal, title="Fecha Hora Cupos"):
    fecha = discord.ui.TextInput(label="DD/MM", placeholder="20/10")
    hora = discord.ui.TextInput(label="HH:MM UTC", placeholder="21:30")
    cupos = discord.ui.TextInput(label="Cupos 1-20", placeholder="20")

    def __init__(self, user_id, actividad, defaults=None):
        super().__init__()
        self.user_id = user_id
        self.actividad = actividad
        if defaults:
            self.fecha.default = defaults.get("fecha") or None
            self.hora.default = defaults.get("hora") or None
            self.cupos.default = defaults.get("cupos") or None

    async def on_submit(self, interaction):
        fecha = str(self.fecha).strip()
        hora = str(self.hora).strip()
        cupos_texto = str(self.cupos).strip()
        errores = []

        fecha_valida = bool(re.fullmatch(r"\d{2}/\d{2}", fecha))
        if fecha_valida:
            try:
                datetime.strptime(f"{fecha}/2000", "%d/%m/%Y")
            except ValueError:
                fecha_valida = False
        if not fecha_valida:
            errores.append("La fecha no es válida. Usa DD/MM, por ejemplo 20/10.")

        hora_valida = bool(
            re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", hora)
        )
        if not hora_valida:
            errores.append("La hora no es válida. Usa HH:MM en formato 24 horas.")

        try:
            cupos = int(cupos_texto)
        except ValueError:
            cupos = 0
        if not 1 <= cupos <= 20:
            errores.append("Los cupos deben ser un número entre 1 y 20.")

        if errores:
            await interaction.response.send_message(
                "\n".join(errores),
                view=FechaCorreccionView(
                    self.user_id,
                    self.actividad,
                    {
                        "fecha": fecha,
                        "hora": hora,
                        "cupos": cupos_texto,
                    },
                ),
                ephemeral=True,
            )
            return

        ping_data[self.user_id] = {
            "actividad": self.actividad,
            "fecha": fecha,
            "hora": hora,
            "cupos": cupos,
            "roles": [],
            "weapons": [],
        }
        await interaction.response.send_message(
            embed=build_roles_embed(self.user_id),
            view=RolesView(self.user_id),
            ephemeral=True,
        )


class ActividadesView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180)
        self.user_id = user_id
        for activity in actividades:
            self.add_item(ActButton(activity))
        self.add_item(AgregarButton())


class ActButton(discord.ui.Button):
    def __init__(self, actividad):
        super().__init__(label=actividad, style=discord.ButtonStyle.secondary)
        self.actividad = actividad

    async def callback(self, interaction):
        await interaction.response.send_modal(
            FechaModal(interaction.user.id, self.actividad)
        )


class AgregarButton(discord.ui.Button):
    def __init__(self):
        super().__init__(
            label="➕ Agregar",
            style=discord.ButtonStyle.success,
            row=1,
        )

    async def callback(self, interaction):
        await interaction.response.send_modal(AgregarModal())


class AgregarModal(discord.ui.Modal, title="Agregar actividad"):
    nombre = discord.ui.TextInput(label="Nombre", placeholder="Ej: ZVZ 20")

    async def on_submit(self, interaction):
        actividades.append(str(self.nombre))
        await interaction.response.send_message(
            f"✅ '{self.nombre}' agregada!",
            ephemeral=True,
        )

class MainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🎯 Crear Nuevo Ping", style=discord.ButtonStyle.primary, custom_id="crear_nuevo_ping_main")
    async def crear(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message(view=ActividadesView(interaction.user.id), embed=discord.Embed(title="Elige actividad", color=0xD4A44A), ephemeral=True)

# --- DEBES AGREGAR UN COMANDO PARA MOSTRAR EL MAINVIEW ---
@bot.command()
async def ping(ctx):
    await ctx.send(embed=discord.Embed(title="Panel de Pings Albion", color=0xD4A44A), view=MainView())

@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

if __name__ == "__main__":
    Thread(target=run_flask, daemon=True).start()
    TOKEN = os.environ.get("TOKEN") or os.environ.get("DISCORD_TOKEN")
    bot.run(TOKEN)
