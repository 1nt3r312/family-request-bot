import discord
from discord.ext import commands
from discord import app_commands
import os
import re
from database import init_db, get_guild_settings, set_guild_settings
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')

# Настраиваем интенты
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

# Создаем класс бота
class FamilyBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        # Загружаем Views, чтобы кнопки работали после перезагрузки
        self.add_view(StartApplicationView())
        self.add_view(PersistentApplicationActionsView())
        
        # Синхронизация слэш-команд
        await self.tree.sync()
        print("✅ Слэш-команды синхронизированы!")

bot = FamilyBot()

# --- МОДАЛЬНОЕ ОКНО (ТЕПЕРЬ ОДНО) ---

class SingleApplicationModal(discord.ui.Modal, title="Заявка в семью"):
    # Discord разрешает максимум 5 полей в одном окне!
    
    real_name = discord.ui.TextInput(
        label="Ваше реальное имя", 
        placeholder="Иван",
        required=True, 
        max_length=50
    )
    
    nickname = discord.ui.TextInput(
        label="Никнейм | Статик", 
        placeholder="Ivan_Ivanov | #12345",
        required=True, 
        max_length=50
    )

    # Объединили возраст и пояс, чтобы влезть в лимит 5 полей
    age_timezone = discord.ui.TextInput(
        label="Возраст и Часовой пояс", 
        placeholder="18 лет, МСК+2",
        required=True, 
        max_length=50
    )

    playtime = discord.ui.TextInput(
        label="Опыт игры на проекте", 
        style=discord.TextStyle.paragraph, # Большое поле
        required=False, 
        max_length=300
    )
    
    source = discord.ui.TextInput(
        label="Откуда о нас узнали?", 
        required=True, 
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild_settings = get_guild_settings(interaction.guild.id)
            if not guild_settings or not guild_settings.get('channel_id'):
                await interaction.response.send_message(
                    "❌ Бот не настроен. Попросите администратора использовать `/setup_channel`.",
                    ephemeral=True
                )
                return

            # Формируем красивый Embed
            embed = discord.Embed(title="Новая заявка в семью", color=0x00ffcc)
            embed.add_field(name="Пользователь", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            
            embed.add_field(name="👤 Реальное имя", value=self.real_name.value, inline=True)
            embed.add_field(name="🎮 Никнейм | Статик", value=self.nickname.value, inline=True)
            embed.add_field(name="⏰ Возраст / Пояс", value=self.age_timezone.value, inline=True)
            embed.add_field(name="⏳ Опыт игры", value=self.playtime.value or "—", inline=False)
            embed.add_field(name="📢 Источник", value=self.source.value, inline=False)
            
            if interaction.user.display_avatar:
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
            
            # ВАЖНО: ID сохраняем в футере для кнопок
            embed.set_footer(text=f"ID: {interaction.user.id} • {interaction.created_at.strftime('%d.%m.%Y %H:%M')}")

            channel_id = int(guild_settings['channel_id'])
            log_channel = bot.get_channel(channel_id)
            
            if log_channel:
                role_id = guild_settings.get('role_id')
                content_msg = f"<@&{role_id}> Новая заявка!" if role_id and role_id != 'None' else "Новая заявка!"
                
                await log_channel.send(content=content_msg, embed=embed)
                await log_channel.send("Действия с заявкой:", view=PersistentApplicationActionsView())
                
                await interaction.response.send_message("✅ Ваша заявка успешно отправлена!", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Канал заявок не найден.", ephemeral=True)
                
        except Exception as e:
            print(f"Ошибка: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при отправке.", ephemeral=True)

# --- VIEWS (КНОПКИ) ---

class PersistentApplicationActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def get_applicant_id(self, interaction: discord.Interaction):
        try:
            history = [msg async for msg in interaction.channel.history(limit=5, before=interaction.message.created_at)]
            target_embed = None
            for msg in history:
                if msg.author == bot.user and msg.embeds:
                    target_embed = msg.embeds[0]
                    self.target_message = msg
                    break
            
            if not target_embed or not target_embed.footer.text:
                return None, None

            match = re.search(r"ID:\s*(\d+)", target_embed.footer.text)
            if match:
                return int(match.group(1)), target_embed
            return None, None
        except Exception as e:
            print(f"Ошибка парсинга ID: {e}")
            return None, None

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="app_action_accept")
    async def accept_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        applicant_id, original_embed = await self.get_applicant_id(interaction)
        
        if not applicant_id:
            await interaction.followup.send("❌ Не удалось найти заявку.", ephemeral=True)
            return

        if interaction.user.id == applicant_id:
             await interaction.followup.send("❌ Нельзя принять свою заявку.", ephemeral=True)
             return

        try:
            if original_embed:
                original_embed.color = 0x00ff00
                original_embed.title = "✅ Заявка принята"
                original_embed.add_field(name="Кем принята", value=interaction.user.mention, inline=False)
                if hasattr(self, 'target_message'):
                    await self.target_message.edit(embed=original_embed)

            await interaction.message.delete()

            guild_settings = get_guild_settings(interaction.guild.id)
            role_added = False
            
            if guild_settings and guild_settings.get('member_role_id') and guild_settings['member_role_id'] != 'None':
                try:
                    member = interaction.guild.get_member(applicant_id)
                    if member:
                        role = interaction.guild.get_role(int(guild_settings['member_role_id']))
                        if role:
                            await member.add_roles(role)
                            role_added = True
                except Exception as role_error:
                    print(f"Ошибка роли: {role_error}")
                    await interaction.channel.send(f"⚠️ Не удалось выдать роль: {role_error}")

            try:
                applicant = await bot.fetch_user(applicant_id)
                msg = f"🎉 Ваша заявка в семью на сервере **{interaction.guild.name}** одобрена!"
                if role_added:
                    msg += "\n✅ Вам выдана роль участника."
                await applicant.send(msg)
            except:
                pass

            await interaction.channel.send(f"✅ {interaction.user.mention} принял заявку от <@{applicant_id}>.")

        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="app_action_reject")
    async def reject_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        applicant_id, original_embed = await self.get_applicant_id(interaction)
        
        if not applicant_id:
            await interaction.followup.send("❌ Не удалось найти заявку.", ephemeral=True)
            return

        try:
            if original_embed:
                original_embed.color = 0xff0000
                original_embed.title = "❌ Заявка отклонена"
                original_embed.add_field(name="Кем отклонена", value=interaction.user.mention, inline=False)
                if hasattr(self, 'target_message'):
                    await self.target_message.edit(embed=original_embed)

            await interaction.message.delete()

            try:
                applicant = await bot.fetch_user(applicant_id)
                await applicant.send(f"😔 Ваша заявка в семью на сервере **{interaction.guild.name}** отклонена.")
            except:
                pass

            await interaction.channel.send(f"🚫 {interaction.user.mention} отклонил заявку от <@{applicant_id}>.")

        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)

class StartApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Подать заявку", style=discord.ButtonStyle.green, custom_id="start_app_btn")
    async def create_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Сразу открываем единственное модальное окно
        await interaction.response.send_modal(SingleApplicationModal())

# --- СЛЭШ КОМАНДЫ ---

@bot.event
async def on_ready():
    init_db()
    print(f"✅ Family Request Bot {bot.user} запущен!")

@bot.tree.command(name="help", description="Показать инструкцию по настройке бота")
async def help_command(interaction: discord.Interaction):
    embed = discord.Embed(title="📖 Инструкция по настройке", color=0x00ff00)
    embed.add_field(name="1. Канал заявок", value="`/setup_channel`", inline=False)
    embed.add_field(name="2. Роль админа (для пинга)", value="`/setup_role_admin`", inline=False)
    embed.add_field(name="3. Роль новичка (автовыдача)", value="`/setup_role_member`", inline=False)
    embed.add_field(name="4. Запуск", value="`/create_application`", inline=False)
    embed.add_field(name="5. Проверка", value="`/settings`", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="setup_channel", description="Установить канал, куда будут приходить заявки")
@app_commands.describe(channel="Выберите текстовый канал")
@app_commands.default_permissions(administrator=True)
async def setup_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    set_guild_settings(interaction.guild.id, channel_id=channel.id)
    await interaction.response.send_message(f"✅ Канал для заявок установлен: {channel.mention}", ephemeral=True)

@bot.tree.command(name="setup_role_admin", description="Установить роль, которую бот будет тегать при новой заявке")
@app_commands.describe(role="Выберите роль администратора/модератора")
@app_commands.default_permissions(administrator=True)
async def setup_role_admin(interaction: discord.Interaction, role: discord.Role):
    set_guild_settings(interaction.guild.id, role_id=role.id)
    await interaction.response.send_message(f"✅ Роль для уведомлений установлена: {role.mention}", ephemeral=True)

@bot.tree.command(name="setup_role_member", description="Установить роль, которая выдается автоматически при принятии")
@app_commands.describe(role="Выберите роль участника семьи")
@app_commands.default_permissions(administrator=True)
async def setup_role_member(interaction: discord.Interaction, role: discord.Role):
    set_guild_settings(interaction.guild.id, member_role_id=role.id)
    await interaction.response.send_message(f"✅ Роль участника (автовыдача) установлена: {role.mention}", ephemeral=True)

@bot.tree.command(name="create_application", description="Создать сообщение с кнопкой для подачи заявки")
@app_commands.default_permissions(administrator=True)
async def create_application(interaction: discord.Interaction):
    embed = discord.Embed(title="📝 Заявка в семью", description="Нажмите кнопку ниже, чтобы заполнить анкету.", color=0x00aaff)
    embed.set_footer(text="Убедитесь, что у вас открыты личные сообщения.")
    
    await interaction.channel.send(embed=embed, view=StartApplicationView())
    await interaction.response.send_message("✅ Система заявок создана!", ephemeral=True)

@bot.tree.command(name="settings", description="Показать текущие настройки бота")
@app_commands.default_permissions(administrator=True)
async def settings(interaction: discord.Interaction):
    s = get_guild_settings(interaction.guild.id) or {}
    embed = discord.Embed(title="⚙️ Настройки сервера", color=0x00aaff)
    
    ch = f"<#{s.get('channel_id')}>" if s.get('channel_id') else "❌ Не настроен"
    r_adm = f"<@&{s.get('role_id')}>" if s.get('role_id') and s.get('role_id') != 'None' else "❌ Не настроена"
    r_mem = f"<@&{s.get('member_role_id')}>" if s.get('member_role_id') and s.get('member_role_id') != 'None' else "❌ Не настроена"
    
    embed.description = f"**📁 Канал заявок:** {ch}\n**🔔 Пинг роль:** {r_adm}\n**👥 Роль новичка:** {r_mem}"
    await interaction.response.send_message(embed=embed, ephemeral=True)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не найден в .env файле!")
    else:
        bot.run(BOT_TOKEN)