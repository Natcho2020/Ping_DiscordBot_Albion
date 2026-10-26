import discord
from discord.ext import commands
import os
import json
import re
from datetime import datetime
from threading import Thread
from flask import Flask

app_flask = Flask(__name__)
PINGS_DB_PATH = "pings.json"

@app_flask.route('/')
def home():
    return "Bot Albion - ONLINE - Pings guardados: " + str(len(pings_db))

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app_flask.run(host="0.0.0.0", port=port)

intents = discord.Intents.default()
intents.message_content = True

actividades = ["Dorados","Roaming","Buffo-Ava","Arenas","Gankeo","Estatica","Masmorra Grupal"]
ping_data = {}
pings_db = {}

ICONS = {"Tanque":"🛡️","Healer":"💚","Dps":"⚔️","Soporte":"🔮"}

def get_icon(role_name):
    for k,v in ICONS.items():
        if role_name.startswith(k):
            return v
    return "▫️"

def load_pings():
    if not os.path.exists(PINGS_DB_PATH):
        print("No existe pings.json, se creará nuevo")
        return {}
    try:
        with open(PINGS_DB_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Limpiar pings viejos que no tienen weapons (los del codigo anterior)
            clean = {}
            for mid, ping in data.items():
                if "weapons" in ping and "roles" in ping:
                    clean[mid] = ping
            if len(clean) != len(data):
                print(f"Limpiados {len(data)-len(clean)} pings viejos incompatibles")
            return clean
    except Exception as e:
        print(f"Error cargando pings.json: {e}, iniciando vacío")
        return {}

def save_pings():
    try:
        with open(PINGS_DB_PATH, "w", encoding="utf-8") as f:
            json.dump(pings_db, f, ensure_ascii=False, indent=2)
        print(f"✅ pings.json guardado con {len(pings_db)} pings")
    except Exception as e:
        print(f"❌ Error guardando json: {e}")

def role_capacity(ping, role_name):
    return ping.get("roles", []).count(role_name)

def number_role_slots(roles):
    totals = {}
    for r in roles: totals[r] = totals.get(r, 0) + 1
    occ = {}
    numbered = []
    for r in roles:
        occ[r] = occ.get(r, 0) + 1
        numbered.append(f"{r} {occ[r]}" if totals[r] > 1 else r)
    return numbered

def role_registration_count(ping, role_name):
    return sum(v == role_name for v in ping.get("registrations", {}).values())

def build_main_embed(ping):
    regs = ping.get("registrations", {})
    role_to_user = {role: uid for uid, role in regs.items()}
    weapons = ping.get("weapons", [])
    roles = ping.get("roles", [])
    
    lines = []
    for i, role_slot in enumerate(roles):
        icon = get_icon(role_slot)
        weapon = weapons[i] if i < len(weapons) else "—"
        user_id = role_to_user.get(role_slot)

        # Si el arma es "—" no la mostramos
        if weapon == "—" or weapon.strip() == "":
            role_text = f"{role_slot}"
        else:
            role_text = f"{role_slot}: {weapon}"

        if user_id:
            lines.append(f"{icon} `{role_text}` <@{user_id}>")
        else:
            lines.append(f"{icon} `{role_text}`")
    
    compo_text = "\n".join(lines)
    embed = discord.Embed(
        title=f"⚔️ {ping['actividad'].upper()} - {ping['fecha']} {ping['hora']} UTC",
        description=f"**Compo ({len(regs)}/{len(roles)})**\n{compo_text}\n\n**Nota:** {ping.get('comentario','')}",
        color=0xD4A44A,
    )
    embed.set_footer(text=f"Creador: {ping.get('creador','?')}")
    return embed

class AlbionBot(commands.Bot):
    async def setup_hook(self):
        stored = load_pings()
        pings_db.update(stored)
        for mid, ping in stored.items():
            try:
                self.add_view(InscripcionView(ping["roles"], int(mid), int(ping["thread_id"])), message_id=int(mid))
            except:
                pass
        self.add_view(MainView())
        print(f"Bot listo. Restaurados: {len(stored)} + MainView persistente")

bot = AlbionBot(command_prefix="!", intents=intents)

class InscripcionView(discord.ui.View):
    def __init__(self, roles, message_id, thread_id):
        super().__init__(timeout=None)
        ping = pings_db.get(str(message_id), {})
        # Crear botones de roles
        for idx, role in enumerate(roles):
            disabled = False
            if ping:
                if role_registration_count(ping, role) >= role_capacity(ping, role):
                    disabled = True
            self.add_item(InscripcionButton(role, message_id, thread_id, idx, disabled))
        # Boton de cancelar
        self.add_item(CancelarButton(message_id, thread_id))

class CancelarButton(discord.ui.Button):
    def __init__(self, message_id, thread_id):
        super().__init__(label="❌ Cancelar mi inscripción", style=discord.ButtonStyle.danger, custom_id=f"cancel_{message_id}", row=1)
        self.message_id = message_id
        self.thread_id = thread_id

    async def callback(self, interaction: discord.Interaction):
        ping = pings_db.get(str(self.message_id))
        if not ping:
            await interaction.response.send_message("Ping no disponible", ephemeral=True)
            return
        
        uid = str(interaction.user.id)
        if uid not in ping.get("registrations", {}):
            await interaction.response.send_message("No estás anotado en ningún rol.", ephemeral=True)
            return

        rol_lib = ping["registrations"].pop(uid)
        save_pings()
        await interaction.response.defer(ephemeral=True)

        # Actualizar hilo y mensaje principal
        try:
            thread = bot.get_channel(self.thread_id) or await bot.fetch_channel(self.thread_id)
            await thread.send(f"{interaction.user.mention} canceló su inscripción como {rol_lib} ❌")
        except: pass

        try:
            channel = bot.get_channel(ping["channel_id"]) or await bot.fetch_channel(ping["channel_id"])
            msg = await channel.fetch_message(self.message_id)
            # Reconstruir vista con botones habilitados de nuevo
            new_view = InscripcionView(ping["roles"], self.message_id, self.thread_id)
            new_embed = build_main_embed(ping)
            await msg.edit(embed=new_embed, view=new_view)
            bot.add_view(new_view, message_id=self.message_id)
        except Exception as e:
            print(f"Error en cancelar: {e}")

        await interaction.followup.send(f"Cancelaste {rol_lib}, tu cupo quedó libre.", ephemeral=True)

class InscripcionButton(discord.ui.Button):
    def __init__(self, role_name, message_id, thread_id, index, disabled=False):
        super().__init__(label=f"Apuntarme: {role_name}", style=discord.ButtonStyle.secondary, custom_id=f"signup_{message_id}_{index}", disabled=disabled)
        self.role_name = role_name
        self.message_id = message_id
        self.thread_id = thread_id

    async def callback(self, interaction: discord.Interaction):
        ping = pings_db.get(str(self.message_id))
        if not ping:
            await interaction.response.send_message("Ping no disponible", ephemeral=True)
            return
        regs = ping.setdefault("registrations", {})
        uid = str(interaction.user.id)
        if uid in regs:
            await interaction.response.send_message(f"Ya estás como {regs[uid]}. Usa Cancelar para cambiar.", ephemeral=True)
            return
        if role_registration_count(ping, self.role_name) >= role_capacity(ping, self.role_name):
            await interaction.response.send_message(f"No quedan plazas para {self.role_name}.", ephemeral=True)
            return
        regs[uid] = self.role_name
        save_pings()
        await interaction.response.defer(ephemeral=True)
        try:
            thread = bot.get_channel(self.thread_id) or await bot.fetch_channel(self.thread_id)
            await thread.send(f"{interaction.user.mention} se apuntó como {self.role_name} ✅")
        except:
            pass
        try:
            channel = bot.get_channel(ping["channel_id"]) or await bot.fetch_channel(ping["channel_id"])
            msg = await channel.fetch_message(self.message_id)
            new_view = InscripcionView(ping["roles"], self.message_id, self.thread_id)
            new_embed = build_main_embed(ping)
            await msg.edit(embed=new_embed, view=new_view)
            bot.add_view(new_view, message_id=self.message_id)
        except Exception as e:
            print(f"Error editando: {e}")
        await interaction.followup.send(f"Te apuntaste como {self.role_name}.", ephemeral=True)

class WeaponModal(discord.ui.Modal, title="Arma para este rol (opcional)"):
    arma = discord.ui.TextInput(
        label="¿Qué arma? (opcional)", 
        placeholder="Ej: Camlann, Bloodletter - Déjalo vacío si no importa", 
        max_length=30,
        required=False
    )
    def __init__(self, user_id, rol):
        super().__init__()
        self.user_id = user_id
        self.rol = rol
    async def on_submit(self, interaction):
        data = ping_data[self.user_id]
        texto_arma = str(self.arma).strip()
        if not texto_arma:
            texto_arma = "—"
        data["roles"].append(self.rol)
        data["weapons"].append(texto_arma)
        await interaction.response.edit_message(embed=build_roles_embed(self.user_id), view=RolesView(self.user_id))

def build_roles_embed(user_id):
    data = ping_data[user_id]
    role_slots = number_role_slots(data["roles"])
    slots = ""
    for i in range(data["cupos"]):
        if i < len(data["roles"]):
            role = data["roles"][i]
            role_slot = role_slots[i]
            weapon = data["weapons"][i]
            # Si es guión, no muestra los dos puntos
            if weapon == "—":
                slots += f"{ICONS.get(role,'')} `{role_slot}`\n"
            else:
                slots += f"{ICONS.get(role,'')} `{role_slot}: {weapon}`\n"
        else:
            slots += f"⬜ Slot {i+1} Vacío\n"
    return discord.Embed(title=f"👥 {data['actividad']} {len(data['roles'])}/{data['cupos']}", description=slots, color=0xD4A44A)

class RolesView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=300)
        self.user_id = user_id
    @discord.ui.button(label="🛡️ Tanque", style=discord.ButtonStyle.secondary)
    async def tanque(self, i, b): await i.response.send_modal(WeaponModal(self.user_id, "Tanque"))
    @discord.ui.button(label="💚 Healer", style=discord.ButtonStyle.secondary)
    async def healer(self, i, b): await i.response.send_modal(WeaponModal(self.user_id, "Healer"))
    @discord.ui.button(label="⚔️ Dps", style=discord.ButtonStyle.secondary)
    async def dps(self, i, b): await i.response.send_modal(WeaponModal(self.user_id, "Dps"))
    @discord.ui.button(label="🔮 Soporte", style=discord.ButtonStyle.secondary)
    async def soporte(self, i, b): await i.response.send_modal(WeaponModal(self.user_id, "Soporte"))
    @discord.ui.button(label="Siguiente →", style=discord.ButtonStyle.success, row=1)
    async def siguiente(self, interaction, button):
        data = ping_data[self.user_id]
        if len(data["roles"]) != data["cupos"]:
            await interaction.response.send_message(f"Llena {data['cupos']} slots", ephemeral=True)
            return
        await interaction.response.edit_message(embed=discord.Embed(title="💬 Elige sala y escribe comentario", description="Elige donde se enviará el @everyone", color=0xD4A44A), view=CanalView(self.user_id, interaction.guild))

class ComentarioModal(discord.ui.Modal, title="Comentario final"):
    coment = discord.ui.TextInput(label="Comentario", required=False, style=discord.TextStyle.long, placeholder="Ej: IP 1400+, salimos de Martlock")
    def __init__(self, user_id): super().__init__(); self.user_id = user_id
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        data = ping_data[self.user_id]
        data["comentario"] = str(self.coment) or "Sin comentario"
        signup_roles = number_role_slots(data["roles"])
        guild = interaction.guild
        target = discord.utils.get(guild.text_channels, name=data["canal_id"]) or interaction.channel
        
        temp_ping = {
            "actividad": data["actividad"], "fecha": data["fecha"], "hora": data["hora"],
            "roles": signup_roles, "weapons": data["weapons"], "registrations": {},
            "comentario": data["comentario"], "creador": interaction.user.display_name
        }
        embed = build_main_embed(temp_ping)

        message = await target.send(content="@everyone", embed=embed)
        thread = await message.create_thread(name=f"Inscripciones {data['actividad']} {data['fecha']}"[:100], auto_archive_duration=60)

        ping = {
            "guild_id": interaction.guild_id, "channel_id": target.id, "thread_id": thread.id,
            "roles": signup_roles, "weapons": data["weapons"], "registrations": {},
            "actividad": data["actividad"], "fecha": data["fecha"], "hora": data["hora"],
            "comentario": data["comentario"], "creador": interaction.user.display_name
        }
        pings_db[str(message.id)] = ping
        save_pings()
        view = InscripcionView(ping["roles"], message.id, thread.id)
        await message.edit(view=view)
        bot.add_view(view, message_id=message.id)
        await thread.send("Hilo de inscripción creado. Pulsa el botón de tu rol en el ping para apuntarte.")
        await interaction.followup.send(f"✅ Ping enviado en {target.mention}", ephemeral=True)

class CanalSelect(discord.ui.Select):
    def __init__(self, user_id, guild):
        self.user_id = user_id
        canales = [c for c in guild.text_channels if c.permissions_for(guild.me).send_messages][:25]
        if not canales: canales = guild.text_channels[:25]
        options = [discord.SelectOption(label=f"#{c.name}", value=c.name) for c in canales]
        super().__init__(placeholder="1. Elige la sala...", options=options, min_values=1, max_values=1)
    async def callback(self, interaction: discord.Interaction):
        ping_data[self.user_id]["canal_id"] = self.values[0]
        await interaction.response.send_message(f"Canal: #{self.values[0]} seleccionado.", view=ComentarioButtonView(self.user_id), ephemeral=True)

class ComentarioButtonView(discord.ui.View):
    def __init__(self, user_id): super().__init__(timeout=300); self.user_id = user_id
    @discord.ui.button(label="💬 Escribir Comentario y Enviar", style=discord.ButtonStyle.success)
    async def escribir(self, interaction, button): await interaction.response.send_modal(ComentarioModal(self.user_id))

class CanalView(discord.ui.View):
    def __init__(self, user_id, guild): super().__init__(timeout=300); self.user_id = user_id; self.add_item(CanalSelect(user_id, guild))

class FechaCorreccionView(discord.ui.View):
    def __init__(self, user_id, actividad, defaults):
        super().__init__(timeout=300); self.user_id = user_id; self.actividad = actividad; self.defaults = dict(defaults)
    @discord.ui.button(label="Corregir datos", style=discord.ButtonStyle.primary)
    async def corregir(self, interaction, button):
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Solo quien inició este ping puede corregir.", ephemeral=True)
            return
        await interaction.response.send_modal(FechaModal(self.user_id, self.actividad, defaults=self.defaults))

class FechaModal(discord.ui.Modal, title="Fecha Hora Cupos"):
    fecha = discord.ui.TextInput(label="DD/MM", placeholder="20/10")
    hora = discord.ui.TextInput(label="HH:MM UTC", placeholder="21:30")
    cupos = discord.ui.TextInput(label="Cupos 1-20", placeholder="20")
    def __init__(self, user_id, actividad, defaults=None):
        super().__init__(); self.user_id = user_id; self.actividad = actividad
        if defaults:
            self.fecha.default = defaults.get("fecha") or None
            self.hora.default = defaults.get("hora") or None
            self.cupos.default = defaults.get("cupos") or None
    async def on_submit(self, interaction):
        fecha = str(self.fecha).strip(); hora = str(self.hora).strip(); cupos_texto = str(self.cupos).strip()
        errores = []
        fecha_valida = bool(re.fullmatch(r"\d{2}/\d{2}", fecha))
        if fecha_valida:
            try: datetime.strptime(f"{fecha}/2000", "%d/%m/%Y")
            except: fecha_valida = False
        if not fecha_valida: errores.append("Fecha inválida. Usa DD/MM")
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", hora): errores.append("Hora inválida. Usa HH:MM")
        try: cupos = int(cupos_texto)
        except: cupos = 0
        if not 1 <= cupos <= 20: errores.append("Cupos 1-20")
        if errores:
            await interaction.response.send_message("\n".join(errores), view=FechaCorreccionView(self.user_id, self.actividad, {"fecha": fecha, "hora": hora, "cupos": cupos_texto}), ephemeral=True)
            return
        ping_data[self.user_id] = {"actividad": self.actividad, "fecha": fecha, "hora": hora, "cupos": cupos, "roles": [], "weapons": []}
        await interaction.response.send_message(embed=build_roles_embed(self.user_id), view=RolesView(self.user_id), ephemeral=True)

class ActividadesView(discord.ui.View):
    def __init__(self, user_id):
        super().__init__(timeout=180); self.user_id = user_id
        for act in actividades: self.add_item(ActButton(act))
        self.add_item(AgregarButton())

class ActButton(discord.ui.Button):
    def __init__(self, actividad): super().__init__(label=actividad, style=discord.ButtonStyle.secondary); self.actividad = actividad
    async def callback(self, interaction): await interaction.response.send_modal(FechaModal(interaction.user.id, self.actividad))

class AgregarButton(discord.ui.Button):
    def __init__(self): super().__init__(label="➕ Agregar", style=discord.ButtonStyle.success, row=1)
    async def callback(self, interaction): await interaction.response.send_modal(AgregarModal())

class AgregarModal(discord.ui.Modal, title="Agregar actividad"):
    nombre = discord.ui.TextInput(label="Nombre", placeholder="Ej: ZVZ 20")
    async def on_submit(self, interaction):
        actividades.append(str(self.nombre))
        await interaction.response.send_message(f"✅ '{self.nombre}' agregada!", ephemeral=True)

class MainView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="🎯 Crear Nuevo Ping", style=discord.ButtonStyle.primary, custom_id="crear_nuevo_ping_main")
    async def crear(self, interaction, button):
        await interaction.response.send_message(view=ActividadesView(interaction.user.id), embed=discord.Embed(title="Elige actividad", color=0xD4A44A), ephemeral=True)

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
