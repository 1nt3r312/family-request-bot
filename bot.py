import discord
from discord.ext import commands
import os
from database import init_db, get_guild_settings, set_guild_settings
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
application_data = {}

# Инициализация базы
init_db()

class ApplicationStep1Modal(discord.ui.Modal, title="Основная информация"):
    real_name = discord.ui.TextInput(label="Ваше реальное имя *", required=True, max_length=50)
    age = discord.ui.TextInput(label="Ваш возраст *", required=True, max_length=3)
    nickname = discord.ui.TextInput(label="Никнейм | Статик *", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        application_data[interaction.user.id] = {
            'real_name': self.real_name.value,
            'age': self.age.value,
            'nickname': self.nickname.value
        }
        await interaction.response.send_message(
            "Первый шаг завершен! Нажмите кнопку ниже чтобы продолжить.",
            view=ApplicationStep2View(),
            ephemeral=True
        )

class ApplicationStep2Modal(discord.ui.Modal, title="Дополнительная информация"):
    playtime = discord.ui.TextInput(label="Как давно играете на проекте?", required=False, max_length=100)
    source = discord.ui.TextInput(label="Как о нас узнали? *", required=True, max_length=100)
    timezone = discord.ui.TextInput(label="Часовой пояс и онлайн *", placeholder="МСК+2, 4-6 часов в день", required=True, max_length=100)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            guild_settings = get_guild_settings(interaction.guild.id)
            if not guild_settings or not guild_settings.get('channel_id'):
                await interaction.response.send_message(
                    "❌ Бот не настроен на этом сервере. Попросите администратора выполнить `!инструкция`",
                    ephemeral=True
                )
                return

            basic_info = application_data.get(interaction.user.id, {})
            if not basic_info:
                await interaction.response.send_message("Данные первой формы не найдены. Начните заново.", ephemeral=True)
                return

            embed = discord.Embed(title="Новая заявка в семью", color=0x00ffcc)
            embed.add_field(name="Пользователь", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            embed.add_field(name="Реальное имя", value=basic_info.get('real_name', '—'), inline=True)
            embed.add_field(name="Возраст", value=basic_info.get('age', '—'), inline=True)
            embed.add_field(name="Никнейм | Статик", value=basic_info.get('nickname', '—'), inline=True)
            embed.add_field(name="Опыт на проекте", value=self.playtime.value or "—", inline=True)
            embed.add_field(name="Источник", value=self.source.value, inline=True)
            embed.add_field(name="Часовой пояс", value=self.timezone.value, inline=True)
            
            embed.set_thumbnail(url=interaction.user.display_avatar.url)
            embed.set_footer(text=f"ID: {interaction.user.id} • {interaction.created_at.strftime('%d.%m.%Y %H:%M')}")

            channel_id = int(guild_settings['channel_id'])
            log_channel = bot.get_channel(channel_id)
            
            if log_channel:
                role_id = guild_settings.get('role_id')
                if role_id:
                    role_mention = f"<@&{role_id}>"
                    await log_channel.send(f"{role_mention} Новая заявка!")
                
                await log_channel.send(embed=embed)
                action_view = ApplicationActionsView(interaction.user.id, interaction.guild.id)
                await log_channel.send("Действия с заявкой:", view=action_view)
                
                if interaction.user.id in application_data:
                    del application_data[interaction.user.id]
                
                await interaction.response.send_message("✅ Ваша заявка успешно отправлена! Ожидайте ответа.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Канал для заявок не найден. Сообщите администратору.", ephemeral=True)
                
        except Exception as e:
            print(f"Ошибка при отправке заявки: {e}")
            await interaction.response.send_message("❌ Произошла ошибка. Попробуйте позже.", ephemeral=True)

class ApplicationStep2View(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label="Продолжить заполнение", style=discord.ButtonStyle.blurple)
    async def continue_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in application_data:
            await interaction.response.send_message("Данные утеряны. Начните заново.", ephemeral=True)
            return
        await interaction.response.send_modal(ApplicationStep2Modal())

class ApplicationActionsView(discord.ui.View):
    def __init__(self, applicant_id, guild_id):
        super().__init__(timeout=None)
        self.applicant_id = applicant_id
        self.guild_id = guild_id
        self.processed = False

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="accept_application")
    async def accept_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processed:
            await interaction.response.send_message("Заявка уже обработана.", ephemeral=True)
            return
            
        try:
            applicant = await bot.fetch_user(self.applicant_id)
            self.processed = True
            for item in self.children:
                item.disabled = True

            original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
            if original_embed:
                original_embed.color = 0x00ff00
                original_embed.title = "Заявка принята!"
                await interaction.message.edit(embed=original_embed, view=None)
            await interaction.message.edit(content="**Заявка принята**", view=self)

            # Выдача роли
            guild_settings = get_guild_settings(self.guild_id)
            role_added = False
            
            if guild_settings and guild_settings.get('member_role_id'):
                try:
                    member = interaction.guild.get_member(self.applicant_id)
                    if member:
                        role = interaction.guild.get_role(int(guild_settings['member_role_id']))
                        if role:
                            await member.add_roles(role)
                            role_added = True
                except Exception as role_error:
                    print(f"Ошибка при выдаче роли: {role_error}")

            embed = discord.Embed(title="✅ Заявка принята!", description=f"Заявка от {applicant.mention} одобрена {interaction.user.mention}.", color=0x00ff00)
            if role_added:
                embed.add_field(name="Роль", value="Успешно выдана!", inline=False)
            await interaction.response.send_message(embed=embed)
            
            try:
                message_text = f"🎉 Ваша заявка в семью была одобрена администратором {interaction.user.name}."
                if role_added:
                    message_text += "\n✅ Вам была выдана роль участника!"
                await applicant.send(message_text)
            except:
                pass
                
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

    @discord.ui.button(label="Отклонить", style=discord.ButtonStyle.danger, custom_id="reject_application")
    async def reject_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.processed:
            await interaction.response.send_message("Заявка уже обработана.", ephemeral=True)
            return
            
        try:
            applicant = await bot.fetch_user(self.applicant_id)
            self.processed = True
            for item in self.children:
                item.disabled = True

            original_embed = interaction.message.embeds[0] if interaction.message.embeds else None
            if original_embed:
                original_embed.color = 0xff0000
                original_embed.title = "Заявка отклонена"
                await interaction.message.edit(embed=original_embed, view=None)
            await interaction.message.edit(content="**Заявка отклонена**", view=self)

            embed = discord.Embed(title="❌ Заявка отклонена", description=f"Заявка от {applicant.mention} отклонена {interaction.user.mention}.", color=0xff0000)
            await interaction.response.send_message(embed=embed)
            
            try:
                await applicant.send(f"😔 Ваша заявка в семью была отклонена администратором {interaction.user.name}.")
            except:
                pass
                
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)

class ApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📝 Подать заявку", style=discord.ButtonStyle.green, custom_id="apply_button")
    async def create_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id in application_data:
            del application_data[interaction.user.id]
        await interaction.response.send_modal(ApplicationStep1Modal())

@bot.command()
async def инструкция(ctx):
    """📖 Показывает инструкцию по настройке бота"""
    embed = discord.Embed(title="📖 Инструкция по настройке Family Request Bot", color=0x00ff00)
    embed.add_field(
        name="1. 🏷️ Настройка канала для заявок",
        value="`!канал #название-канала`",
        inline=False
    )
    embed.add_field(
        name="2. 🔔 Настройка роли для уведомлений", 
        value="`!роль_админ @РольАдминистратора`",
        inline=False
    )
    embed.add_field(
        name="3. 👥 Настройка роли участника",
        value="`!роль_участник @РольУчастника`", 
        inline=False
    )
    embed.add_field(
        name="4. 🎯 Создать сообщение с заявкой",
        value="`!создать_заявку`",
        inline=False
    )
    embed.add_field(
        name="5. 🔧 Проверить настройки",
        value="`!настройки`",
        inline=False
    )
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def канал(ctx, канал: discord.TextChannel):
    """🏷️ Установить канал для заявок"""
    set_guild_settings(ctx.guild.id, channel_id=канал.id)
    await ctx.send(f"✅ Канал для заявок установлен: {канал.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def роль_админ(ctx, роль: discord.Role):
    """🔔 Установить роль для уведомлений о новых заявках"""
    set_guild_settings(ctx.guild.id, role_id=роль.id)
    await ctx.send(f"✅ Роль для уведомлений установлена: {роль.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def роль_участник(ctx, роль: discord.Role):
    """👥 Установить роль которую выдавать при принятии заявки"""
    set_guild_settings(ctx.guild.id, member_role_id=роль.id)
    await ctx.send(f"✅ Роль участника установлена: {роль.mention}")

@bot.command()
async def создать_заявку(ctx):
    """🎯 Создаёт сообщение с кнопкой для подачи заявок"""
    guild_settings = get_guild_settings(ctx.guild.id)
    if not guild_settings or not guild_settings.get('channel_id'):
        await ctx.send("❌ Сначала настройте бота командой `!инструкция`")
        return
        
    embed = discord.Embed(title="📝 Заявка в нашу семью", description="Нажмите кнопку ниже чтобы подать заявку на вступление", color=0x00aaff)
    embed.add_field(name="Процесс", value="• Заполнение анкеты\n• Рассмотрение администрацией\n• Получение ответа", inline=False)
    embed.set_footer(text="Заполняйте поля внимательно!")
    
    await ctx.send(embed=embed, view=ApplicationView())
    await ctx.send("✅ Система заявок активирована!", delete_after=5)

@bot.command()
async def настройки(ctx):
    """🔧 Показывает текущие настройки бота"""
    guild_settings = get_guild_settings(ctx.guild.id)
    
    embed = discord.Embed(title="⚙️ Текущие настройки бота", color=0x00aaff)
    
    if guild_settings and guild_settings.get('channel_id'):
        embed.add_field(name="📁 Канал заявок", value=f"<#{guild_settings['channel_id']}>", inline=True)
    else:
        embed.add_field(name="📁 Канал заявок", value="❌ Не настроен", inline=True)
        
    if guild_settings and guild_settings.get('role_id'):
        embed.add_field(name="🔔 Роль уведомлений", value=f"<@&{guild_settings['role_id']}>", inline=True)
    else:
        embed.add_field(name="🔔 Роль уведомлений", value="❌ Не настроена", inline=True)
        
    if guild_settings and guild_settings.get('member_role_id'):
        embed.add_field(name="👥 Роль участника", value=f"<@&{guild_settings['member_role_id']}>", inline=True)
    else:
        embed.add_field(name="👥 Роль участника", value="❌ Не настроена", inline=True)
    
    await ctx.send(embed=embed)

@bot.event
async def on_ready():
    print(f"✅ Family Request Bot {bot.user} запущен и готов к работе!")
    bot.add_view(ApplicationView())
    bot.add_view(ApplicationActionsView(None, None))

@bot.event
async def on_guild_join(guild):
    print(f"✅ Family Request Bot добавлен на сервер: {guild.name} (ID: {guild.id})")
    
    # Отправляем сообщение в общий канал
    for channel in guild.text_channels:
        if channel.permissions_for(guild.me).send_messages:
            embed = discord.Embed(title="🎉 Family Request Bot добавлен на сервер!", color=0x00ff00)
            embed.description = "Бот для управления заявками в семью/гильдию"
            embed.add_field(name="Быстрый старт", value="1. `!инструкция` - показать инструкцию\n2. Настроить каналы и роли\n3. `!создать_заявку` - активировать систему", inline=False)
            await channel.send(embed=embed)
            break

if __name__ == "__main__":
    bot.run(BOT_TOKEN)