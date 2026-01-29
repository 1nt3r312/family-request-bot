import discord
from discord.ext import commands
import os
import re
from database import init_db, get_guild_settings, set_guild_settings
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# Временное хранилище для данных между шагом 1 и 2
# Внимание: При перезагрузке бота эти данные очистятся!
application_data = {}

# --- МОДАЛЬНЫЕ ОКНА ---

class ApplicationStep1Modal(discord.ui.Modal, title="Основная информация"):
    real_name = discord.ui.TextInput(label="Ваше реальное имя *", required=True, max_length=50)
    age = discord.ui.TextInput(label="Ваш возраст *", required=True, max_length=3)
    nickname = discord.ui.TextInput(label="Никнейм | Статик *", required=True, max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        # Сохраняем данные первого шага
        application_data[interaction.user.id] = {
            'real_name': self.real_name.value,
            'age': self.age.value,
            'nickname': self.nickname.value
        }
        # Отправляем кнопку для перехода ко второму шагу
        await interaction.response.send_message(
            "Первый шаг завершен! Нажмите кнопку ниже чтобы продолжить.",
            view=ContinueApplicationView(),
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
                    "❌ Бот не настроен на этом сервере. Администратор должен установить канал заявок.",
                    ephemeral=True
                )
                return

            basic_info = application_data.get(interaction.user.id)
            if not basic_info:
                await interaction.response.send_message("❌ Данные первой формы устарели или утеряны. Пожалуйста, начните заново.", ephemeral=True)
                return

            # Формируем красивый Embed
            embed = discord.Embed(title="Новая заявка в семью", color=0x00ffcc)
            embed.add_field(name="Пользователь", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
            embed.add_field(name="Реальное имя", value=basic_info.get('real_name', '—'), inline=True)
            embed.add_field(name="Возраст", value=basic_info.get('age', '—'), inline=True)
            embed.add_field(name="Никнейм | Статик", value=basic_info.get('nickname', '—'), inline=True)
            embed.add_field(name="Опыт на проекте", value=self.playtime.value or "—", inline=True)
            embed.add_field(name="Источник", value=self.source.value, inline=True)
            embed.add_field(name="Часовой пояс", value=self.timezone.value, inline=True)
            
            if interaction.user.display_avatar:
                embed.set_thumbnail(url=interaction.user.display_avatar.url)
            
            # ВАЖНО: ID сохраняем в футере, чтобы потом считать его кнопками
            embed.set_footer(text=f"ID: {interaction.user.id} • {interaction.created_at.strftime('%d.%m.%Y %H:%M')}")

            channel_id = int(guild_settings['channel_id'])
            log_channel = bot.get_channel(channel_id)
            
            if log_channel:
                role_id = guild_settings.get('role_id')
                content_msg = f"<@&{role_id}> Новая заявка!" if role_id and role_id != 'None' else "Новая заявка!"
                
                await log_channel.send(content=content_msg, embed=embed)
                # Отправляем меню действий (оно теперь Persistent)
                await log_channel.send("Действия с заявкой:", view=PersistentApplicationActionsView())
                
                # Чистим память
                if interaction.user.id in application_data:
                    del application_data[interaction.user.id]
                
                await interaction.response.send_message("✅ Ваша заявка успешно отправлена! Ожидайте ответа.", ephemeral=True)
            else:
                await interaction.response.send_message("❌ Канал для заявок не найден. Сообщите администратору.", ephemeral=True)
                
        except Exception as e:
            print(f"Ошибка при отправке заявки: {e}")
            await interaction.response.send_message("❌ Произошла ошибка при обработке. Попробуйте позже.", ephemeral=True)

# --- VIEWS (КНОПКИ) ---

class ContinueApplicationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Кнопка не исчезнет

    @discord.ui.button(label="Продолжить заполнение", style=discord.ButtonStyle.blurple, custom_id="app_continue_btn")
    async def continue_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in application_data:
            await interaction.response.send_message("❌ Данные утеряны (возможно, бот перезагружался). Начните заполнение заново.", ephemeral=True)
            return
        await interaction.response.send_modal(ApplicationStep2Modal())

class PersistentApplicationActionsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Важно для сохранения работы после перезагрузки

    async def get_applicant_id(self, interaction: discord.Interaction):
        """Извлекает ID подавшего заявку из футера Embed сообщения"""
        try:
            # Ищем сообщение с Embed выше кнопок (обычно это предыдущее сообщение или сообщение, к которому прикреплен view)
            # В твоем коде view отправляется отдельным сообщением "Действия с заявкой:"
            # Нам нужно найти сообщение с Embed, которое находится ПЕРЕД сообщением с кнопками.
            
            history = [msg async for msg in interaction.channel.history(limit=5, before=interaction.message.created_at)]
            target_embed = None
            
            # Ищем ближайшее сообщение с Embed от бота
            for msg in history:
                if msg.author == bot.user and msg.embeds:
                    target_embed = msg.embeds[0]
                    self.target_message = msg # Сохраняем ссылку на сообщение с эмбедом
                    break
            
            if not target_embed or not target_embed.footer.text:
                return None, None

            # Парсим ID из текста "ID: 123456789..."
            footer_text = target_embed.footer.text
            match = re.search(r"ID:\s*(\d+)", footer_text)
            if match:
                return int(match.group(1)), target_embed
            return None, None
        except Exception as e:
            print(f"Ошибка парсинга ID: {e}")
            return None, None

    @discord.ui.button(label="Принять", style=discord.ButtonStyle.success, custom_id="app_action_accept")
    async def accept_application(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer() # Даем боту время подумать
        
        applicant_id, original_embed = await self.get_applicant_id(interaction)
        
        if not applicant_id:
            await interaction.followup.send("❌ Не удалось найти заявку или ID пользователя.", ephemeral=True)
            return

        # Проверка: не нажал ли кнопку сам подающий (на всякий случай)
        if interaction.user.id == applicant_id:
             await interaction.followup.send("❌ Вы не можете принять свою заявку.", ephemeral=True)
             return

        try:
            # Обновляем Embed (зеленый цвет)
            if original_embed:
                original_embed.color = 0x00ff00
                original_embed.title = "✅ Заявка принята"
                original_embed.add_field(name="Кем принята", value=interaction.user.mention, inline=False)
                if hasattr(self, 'target_message'):
                    await self.target_message.edit(embed=original_embed)

            # Удаляем кнопки
            await interaction.message.delete()

            # Выдача роли
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
                    print(f"Ошибка при выдаче роли: {role_error}")
                    await interaction.channel.send(f"⚠️ Не удалось выдать роль: {role_error}")

            # Уведомление в ЛС
            try:
                applicant = await bot.fetch_user(applicant_id)
                msg = f"🎉 Ваша заявка в семью на сервере **{interaction.guild.name}** была одобрена!"
                if role_added:
                    msg += "\n✅ Вам выдана роль участника."
                await applicant.send(msg)
            except:
                pass # ЛС закрыто

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
            # Обновляем Embed (красный цвет)
            if original_embed:
                original_embed.color = 0xff0000
                original_embed.title = "❌ Заявка отклонена"
                original_embed.add_field(name="Кем отклонена", value=interaction.user.mention, inline=False)
                if hasattr(self, 'target_message'):
                    await self.target_message.edit(embed=original_embed)

            # Удаляем кнопки
            await interaction.message.delete()

            # Уведомление в ЛС
            try:
                applicant = await bot.fetch_user(applicant_id)
                await applicant.send(f"😔 Ваша заявка в семью на сервере **{interaction.guild.name}** была отклонена.")
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
        # Очищаем старые данные если есть
        if interaction.user.id in application_data:
            del application_data[interaction.user.id]
        await interaction.response.send_modal(ApplicationStep1Modal())

# --- КОМАНДЫ ---

@bot.event
async def on_ready():
    init_db()
    print(f"✅ Family Request Bot {bot.user} запущен!")
    # Регистрируем Views чтобы они работали после перезагрузки
    bot.add_view(StartApplicationView())
    bot.add_view(ContinueApplicationView())
    bot.add_view(PersistentApplicationActionsView())

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас недостаточно прав для этой команды.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(f"❌ Пропущен аргумент. Использование: `{ctx.prefix}{ctx.command.name} {ctx.command.signature}`")
    else:
        print(f"Ошибка команды: {error}")

@bot.command()
async def инструкция(ctx):
    """📖 Показывает инструкцию по настройке бота"""
    embed = discord.Embed(title="📖 Инструкция по настройке", color=0x00ff00)
    embed.add_field(name="1. Канал заявок", value="`!канал #название`", inline=False)
    embed.add_field(name="2. Роль админа (для пинга)", value="`!роль_админ @Роль`", inline=False)
    embed.add_field(name="3. Роль новичка (автовыдача)", value="`!роль_участник @Роль`", inline=False)
    embed.add_field(name="4. Запуск", value="`!создать_заявку`", inline=False)
    await ctx.send(embed=embed)

@bot.command()
@commands.has_permissions(administrator=True)
async def канал(ctx, канал: discord.TextChannel):
    set_guild_settings(ctx.guild.id, channel_id=канал.id)
    await ctx.send(f"✅ Канал для заявок установлен: {канал.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def роль_админ(ctx, роль: discord.Role):
    set_guild_settings(ctx.guild.id, role_id=роль.id)
    await ctx.send(f"✅ Роль для уведомлений: {роль.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def роль_участник(ctx, роль: discord.Role):
    set_guild_settings(ctx.guild.id, member_role_id=роль.id)
    await ctx.send(f"✅ Роль участника (автовыдача): {роль.mention}")

@bot.command()
@commands.has_permissions(administrator=True)
async def создать_заявку(ctx):
    await ctx.message.delete() # Удаляем сообщение команды для красоты
    embed = discord.Embed(title="📝 Заявка в семью", description="Нажмите кнопку ниже, чтобы начать заполнение анкеты.", color=0x00aaff)
    embed.set_footer(text="Убедитесь, что у вас открыты личные сообщения.")
    await ctx.send(embed=embed, view=StartApplicationView())

@bot.command()
async def настройки(ctx):
    s = get_guild_settings(ctx.guild.id) or {}
    embed = discord.Embed(title="⚙️ Настройки", color=0x00aaff)
    
    ch = f"<#{s.get('channel_id')}>" if s.get('channel_id') else "❌ Нет"
    r_adm = f"<@&{s.get('role_id')}>" if s.get('role_id') and s.get('role_id') != 'None' else "❌ Нет"
    r_mem = f"<@&{s.get('member_role_id')}>" if s.get('member_role_id') and s.get('member_role_id') != 'None' else "❌ Нет"
    
    embed.description = f"**Канал:** {ch}\n**Пинг роль:** {r_adm}\n**Роль новичка:** {r_mem}"
    await ctx.send(embed=embed)

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("❌ Ошибка: BOT_TOKEN не найден в .env файле!")
    else:
        bot.run(BOT_TOKEN)