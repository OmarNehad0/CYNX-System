import discord
from discord.ext import commands, tasks
import os
from flask import Flask
from threading import Thread
import logging
from discord import app_commands
import json
import random
import asyncio
from datetime import datetime, timedelta
from PIL import Image, ImageDraw, ImageFont
import io
import math
import subprocess
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import discord
from discord.ext import commands
import asyncio  # Ensure asyncio is imported
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service as ChromeService
from webdriver_manager.chrome import ChromeDriverManager
from playwright.async_api import async_playwright
import re
import hashlib
import aiohttp
from urllib.parse import urlencode
from http.cookiejar import CookieJar
from discord.ui import View, Button, Modal, TextInput
import pymongo
import gspread
from discord import Embed, Interaction
from pymongo import MongoClient, ReturnDocument

logging.basicConfig(level=logging.INFO)

bumper_task = None  # Ensure bumper_task is globally defined

# Set up intents
intents = discord.Intents.default()
intents.members = True  # For member join tracking
intents.message_content = True  # Required for prefix commands

bot = commands.Bot(command_prefix="!", intents=intents)

# Connect to MongoDB using the provided URI from Railway
mongo_uri = os.getenv("MONGO_URI")  # You should set this in your Railway environment variables
client = MongoClient(mongo_uri)

# Choose your database
db = client['MongoDB']  # Replace with the name of your database

# Access collections (equivalent to Firestore collections)
wallets_collection = db['wallets']
orders_collection = db['orders']
counters_collection = db["order_counters"]  # New collection to track order ID

# The fixed orders posting channel
ORDERS_CHANNEL_ID = 1208792946401615893
# Allowed roles for commands
ALLOWED_ROLES = {1208792946430836736, 1208792946401615900, 1211406868480532571, 1208792946401615902}

def has_permission(user: discord.Member):
    return any(role.id in ALLOWED_ROLES for role in user.roles)

async def log_command(interaction: discord.Interaction, command_name: str, details: str):
    # Mapping of servers to their respective log channels
    LOG_CHANNELS = {
        1208792946401615893: 1345311951747813450  # Server 1 → Log Channel 1
    }

    for guild_id, channel_id in LOG_CHANNELS.items():
        log_guild = interaction.client.get_guild(guild_id)  # Get the guild
        if log_guild:
            log_channel = log_guild.get_channel(channel_id)  # Get the log channel
            if log_channel:
                embed = discord.Embed(title="📜 Command Log", color=discord.Color.red())
                embed.add_field(name="👤 User", value=f"{interaction.user.mention} ({interaction.user.id})", inline=False)
                embed.add_field(name="💻 Command", value=command_name, inline=False)
                embed.add_field(name="📜 Details", value=details, inline=False)
                embed.set_footer(text=f"Used in: {interaction.guild.name}", icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
                await log_channel.send(embed=embed)
            else:
                print(f"⚠️ Log channel not found in {log_guild.name} ({channel_id})")
        else:
            print(f"⚠️ Log guild not found: {guild_id}")

# Syncing command tree for slash commands
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

def get_wallet(user_id):
    # Attempt to fetch the user's wallet data from MongoDB
    wallet_data = wallets_collection.find_one({"user_id": user_id})

    # If the wallet doesn't exist in the database, create a new one with default values
    if not wallet_data:
        print(f"Wallet not found for {user_id}, creating new wallet...")
        wallet_data = {
            "user_id": user_id,
            "wallet": 0,    # Initialize with 0M
            "spent": 0,     # Initialize with 0M
            "deposit": 0    # Initialize with 0M
        }
        # Insert the new wallet into the database
        wallets_collection.insert_one(wallet_data)
        print(f"New wallet created for {user_id}: {wallet_data}")

    return wallet_data

# Function to update wallet in MongoDB
def update_wallet(user_id, field, value):
    # Make sure the wallet document exists before updating
    wallet_data = get_wallet(user_id)
    
    # If the wallet does not contain the required field, we initialize it with the correct value
    if field not in wallet_data:
        wallet_data[field] = 0  # Initialize the field if missing

    # Update wallet data by incrementing the field value
    wallets_collection.update_one(
        {"user_id": user_id},
        {"$inc": {field: value}},  # Increment the field (e.g., wallet, deposit, spent)
        upsert=True  # Insert a new document if one doesn't exist
    )

@bot.tree.command(name="wallet", description="Check a user's wallet balance")
async def wallet(interaction: discord.Interaction, user: discord.Member = None):
    # Define role IDs
    self_only_roles = {1212728950606794763, 1208822252850909234} 
    allowed_roles = {1208792946430836736, 1208792946401615900, 1211406868480532571, 1208792946401615902}

    # Check if user has permission
    user_roles = {role.id for role in interaction.user.roles}
    has_self_only_role = bool(self_only_roles & user_roles)  # User has at least one self-only role
    has_allowed_role = bool(allowed_roles & user_roles)  # User has at least one allowed role

    # If user has no valid role, deny access
    if not has_self_only_role and not has_allowed_role:
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    # If user has only a self-only role (and not an allowed role), force them to check their own wallet
    if has_self_only_role and not has_allowed_role:
        user = interaction.user  

    # Default to interaction user if no target user is specified
    if user is None:
        user = interaction.user

    # Fetch wallet data
    user_id = str(user.id)
    wallet_data = get_wallet(user_id)
    
    # Default missing fields to 0
    deposit_value = wallet_data.get('deposit', 0)
    wallet_value = wallet_data.get('wallet', 0)
    spent_value = wallet_data.get('spent', 0)

    # Get user's avatar (fallback to default image)
    default_thumbnail = "https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&="
    thumbnail_url = user.avatar.url if user.avatar else default_thumbnail

    # Create embed message
    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=thumbnail_url)
    embed.add_field(name="<:70023pepepresident:1321482641475637349> Deposit", value=f"```💵 {deposit_value}M```", inline=False)
    embed.add_field(name="<:200pxBlood_money_detail:1210284746966306846> Wallet", value=f"```🤑 {wallet_value}M```", inline=False)
    embed.add_field(name="<:wolf:1261406634802941994> Spent", value=f"```🎃 {spent_value}M```", inline=False)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")

    # Ensure requester avatar exists
    requester_avatar = interaction.user.avatar.url if interaction.user.avatar else default_thumbnail
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=requester_avatar)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="add_remove_spent", description="Add or remove spent value from a user's wallet")
@app_commands.choices(action=[
    discord.app_commands.Choice(name="Add", value="add"),
    discord.app_commands.Choice(name="Remove", value="remove")
])
async def add_remove_spent(interaction: discord.Interaction, user: discord.Member, action: str, value: float):
    if not has_permission(interaction.user):  # Check role permissions
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(user.id)
    wallet_data = get_wallet(user_id)
    
    # Default missing fields
    spent_value = wallet_data.get("spent", 0)

    if action == "remove":
        if spent_value < value:
            await interaction.response.send_message("⚠ Insufficient spent balance to remove!", ephemeral=True)
            return
        update_wallet(user_id, "spent", -value)
    else:
        update_wallet(user_id, "spent", value)

    # Fetch updated wallet data
    updated_wallet = get_wallet(user_id)
    spent_value = updated_wallet.get("spent", 0)
    
    # Check and assign roles for spending milestones
    await check_and_assign_roles(user, spent_value, interaction.client)

    # Create embed response
    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(name="<:wolf:1261406634802941994> Spent", value=f"```🎃 {spent_value:,}M```", inline=False)
    embed.set_footer(text=f"Updated by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)

    await interaction.response.send_message(f"✅ {action.capitalize()}ed {value:,}M spent.", embed=embed)
    await log_command(interaction, "add_remove_spent", f"User: {user.mention} | Action: {action} | Value: {value:,}M")

async def check_and_assign_roles(user: discord.Member, spent_value: int, client):
    """
    Checks user's spent amount and assigns the correct role if they reach milestones.
    Sends a congrats message in the announcement channel.
    """
    role_milestones = {
        1: 1212554296294514768,  # 1M+
        4000: 1210262407994413176,  # 4M+
        5000: 1210262187638132806,  # 5M+
        7000: 1210090197845282908,  # 7M+
        9000: 1210088939919118336,  # 9M+
        14000: 1209962980179968010  # 14M+
    }

    # Fetch the correct channel
    congrats_channel = client.get_channel(1210687108457701468)  # Ensure it's the correct ID
    if congrats_channel is None:
        try:
            congrats_channel = await client.fetch_channel(1210687108457701468)  
            print(f"[DEBUG] Successfully fetched channel: {congrats_channel.name} ({congrats_channel.id})")
        except discord.NotFound:
            print("[ERROR] Channel not found in API!")
            return
        except discord.Forbidden:
            print("[ERROR] Bot lacks permission to fetch the channel!")
            return
        except Exception as e:
            print(f"[ERROR] Unexpected error fetching channel: {e}")
            return

    print(f"[DEBUG] Checking roles for {user.display_name} | Spent: {spent_value}")

    for threshold, role_id in sorted(role_milestones.items()):
        role = user.guild.get_role(role_id)
        if not role:
            print(f"[ERROR] Role ID {role_id} not found in guild!")
            continue
        
        print(f"[DEBUG] Checking role {role.name} ({role_id}) for threshold {threshold}")

        if spent_value >= threshold and role not in user.roles:
            print(f"[DEBUG] Assigning role {role.name} to {user.display_name}")
            await user.add_roles(role)

            # Send congrats message
            print(f"[DEBUG] Sending congrats message for {user.display_name}")
            embed = discord.Embed(
            title="🎉 Congratulations!",
            description=f"{user.mention} has reached **{threshold:,}M+** spent and earned a new role!",
            color=discord.Color.gold()
            )
            embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
            embed.add_field(name="🏅 New Role Earned:", value=f"{role.mention}", inline=False)
            embed.set_footer(text="Keep spending to reach new Lifetime Rank! ✨", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif" )
            embed.set_author(name="✅ Cynx System ✅", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")
            await congrats_channel.send(embed=embed)


async def watch_wallet_updates(bot):
    """
    Watches the MongoDB 'wallets' collection for changes.
    Triggers check_and_assign_roles() when 'spent' updates.
    """
    pipeline = [{"$match": {"operationType": "update"}}]  # Only watch updates
    change_stream = wallets_collection.watch(pipeline)

    async for change in change_stream:
        try:
            user_id = change["documentKey"]["user_id"]  # Get user ID
            updated_fields = change["updateDescription"]["updatedFields"]

            # Check if 'spent' value was modified
            if "spent" in updated_fields:
                spent_value = updated_fields["spent"]
                
                # Fetch the Discord user from the bot
                guild = bot.get_guild(YOUR_GUILD_ID)  # Replace with your server ID
                user = guild.get_member(int(user_id))

                if user:
                    print(f"[DEBUG] Spent updated for {user.display_name}: {spent_value}M")
                    await check_and_assign_roles(user, spent_value, bot)
                else:
                    print(f"[ERROR] User {user_id} not found in guild!")

        except Exception as e:
            print(f"[ERROR] Error in MongoDB watch: {e}")
@bot.event
async def on_ready():
    print(f"✅ {bot.user} is now online!")
    
    # Start watching MongoDB for wallet updates
    asyncio.create_task(watch_wallet_updates(bot))


# /wallet_add_remove command
@bot.tree.command(name="wallet_add_remove", description="Add or remove value from a user's wallet")
@app_commands.choices(action=[
    discord.app_commands.Choice(name="Add", value="add"),
    discord.app_commands.Choice(name="Remove", value="remove")
])
async def wallet_add_remove(interaction: discord.Interaction, user: discord.Member, action: str, value: float):  
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    user_id = str(user.id)
    
    # Fetch wallet data or default to zero if not found
    wallet_data = get_wallet(user_id) or {"wallet": 0, "deposit": 0, "spent": 0}
    
    # Get individual values with defaults
    wallet_value = wallet_data.get("wallet", 0)
    deposit_value = wallet_data.get("deposit", 0)
    spent_value = wallet_data.get("spent", 0)

    # Action handling
    if action == "remove":
        if wallet_value < value:
            await interaction.response.send_message("⚠ Insufficient balance to remove!", ephemeral=True)
            return
        update_wallet(user_id, "wallet", -value)
    else:
        update_wallet(user_id, "wallet", value)

    # Fetch updated values
    updated_wallet = get_wallet(user_id) or {"wallet": 0, "deposit": 0, "spent": 0}
    wallet_value = updated_wallet.get("wallet", 0)
    deposit_value = updated_wallet.get("deposit", 0)
    spent_value = updated_wallet.get("spent", 0)

    # Embed with modern design
    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)

    embed.add_field(name="<:70023pepepresident:1321482641475637349> Deposit", value=f"```💵 {deposit_value:,}M```", inline=False)
    embed.add_field(name="<:200pxBlood_money_detail:1210284746966306846> Wallet", value=f"```🤑 {wallet_value:,}M```", inline=False)
    embed.add_field(name="<:wolf:1261406634802941994> Spent", value=f"```🎃 {spent_value:,}M```", inline=False)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)
    
    await interaction.response.send_message(f"✅ {action.capitalize()}ed {value:,}M.", embed=embed)
    await log_command(interaction, "wallet_add_remove", f"User: {user.mention} | Action: {action} | Value: {value:,}M")

@bot.tree.command(name="deposit", description="Set or remove a user's deposit value")
@app_commands.choices(action=[
    discord.app_commands.Choice(name="Set", value="set"),
    discord.app_commands.Choice(name="Remove", value="remove")
])
async def deposit(interaction: discord.Interaction, user: discord.Member, action: str, value: int):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    user_id = str(user.id)
    
    # Fetch current wallet data
    wallet_data = get_wallet(user_id)

    # Ensure the deposit field exists
    current_deposit = wallet_data.get("deposit", 0)

    if action == "set":
        new_deposit = current_deposit + value  # Add the deposit value
    elif action == "remove":
        if value > current_deposit:
            await interaction.response.send_message(f"⚠ Cannot remove {value}M. The user only has {current_deposit}M in deposit.", ephemeral=True)
            return
        new_deposit = current_deposit - value  # Subtract the deposit value

    # Update deposit value in MongoDB
    update_wallet(user_id, "deposit", new_deposit - current_deposit)

    # Fetch updated wallet data
    updated_wallet = get_wallet(user_id)

    # Format values
    deposit_value = f"```💵 {updated_wallet['deposit']:,}M```"
    wallet_value = f"```🤑 {updated_wallet['wallet']:,}M```"
    spent_value = f"```🎃 {updated_wallet['spent']:,}M```"

    # Create an embed
    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(name="<:70023pepepresident:1321482641475637349> Deposit", value=deposit_value, inline=False)
    embed.add_field(name="<:200pxBlood_money_detail:1210284746966306846> Wallet", value=wallet_value, inline=False)
    embed.add_field(name="<:wolf:1261406634802941994> Spent", value=spent_value, inline=False)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    # Send response
    await interaction.response.send_message(f"✅ {action.capitalize()}ed deposit value for {user.name} by {value:,}M.", embed=embed)
    await log_command(interaction, "Deposit Set/Remove", f"User: {user.mention} (`{user.id}`)\nAction: {action.capitalize()}\nAmount: {value:,}M")


@bot.tree.command(name="tip", description="Tip M to another user.")
@app_commands.describe(user="User to tip", value="Value in M")
async def tip(interaction: discord.Interaction, user: discord.Member, value: int):
    sender_id = str(interaction.user.id)  # Convert IDs to strings for MongoDB
    recipient_id = str(user.id)

    # Fetch wallet data or default to zero if not found
    sender_wallet = get_wallet(sender_id) or {"wallet": 0, "deposit": 0, "spent": 0}
    recipient_wallet = get_wallet(recipient_id) or {"wallet": 0, "deposit": 0, "spent": 0}

    # Ensure sender has enough balance
    if sender_wallet["wallet"] < value:
        await interaction.response.send_message("❌ You don't have enough M to tip!", ephemeral=True)
        return

    # Update wallets in MongoDB
    update_wallet(sender_id, "wallet", -value)  # Subtract from sender
    update_wallet(recipient_id, "wallet", value)  # Add to recipient

    # Fetch updated data after transaction
    sender_wallet = get_wallet(sender_id) or {"wallet": 0, "deposit": 0, "spent": 0}
    recipient_wallet = get_wallet(recipient_id) or {"wallet": 0, "deposit": 0, "spent": 0}

    # Tip message (public)
    tip_message = f"💸 {interaction.user.mention} tipped {user.mention} **{value:,}M**!"

    # Format numbers with commas (e.g., 1,000M)
    sender_deposit = f"```💵 {sender_wallet['deposit']:,}M```"
    sender_wallet_value = f"```🤑 {sender_wallet['wallet']:,}M```"
    sender_spent = f"```🎃 {sender_wallet['spent']:,}M```"

    recipient_deposit = f"```💵 {recipient_wallet['deposit']:,}M```"
    recipient_wallet_value = f"```🤑 {recipient_wallet['wallet']:,}M```"
    recipient_spent = f"```🎃 {recipient_wallet['spent']:,}M```"

    # Sender's wallet embed
    sender_embed = discord.Embed(title=f"{interaction.user.display_name}'s Updated Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    sender_embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)
    sender_embed.add_field(name="<:70023pepepresident:1321482641475637349> Deposit", value=sender_deposit, inline=False)
    sender_embed.add_field(name="<:200pxBlood_money_detail:1210284746966306846> Wallet", value=sender_wallet_value, inline=False)
    sender_embed.add_field(name="<:wolf:1261406634802941994> Spent", value=sender_spent, inline=False)
    sender_embed.set_footer(text=f"Tip sent to {user.display_name}", icon_url=user.avatar.url)
    sender_embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67c3c8ab&is=67c2772b&hm=bb9222e70e1ddc5d63f9c5c4452b9499a07cbab1d0c501fcf4cc6e8a060d736d&=")
    # Recipient's wallet embed
    recipient_embed = discord.Embed(title=f"{user.display_name}'s Updated Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    recipient_embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    recipient_embed.add_field(name="<:70023pepepresident:1321482641475637349> Deposit", value=recipient_deposit, inline=False)
    recipient_embed.add_field(name="<:200pxBlood_money_detail:1210284746966306846> Wallet", value=recipient_wallet_value, inline=False)
    recipient_embed.add_field(name="<:wolf:1261406634802941994> Spent", value=recipient_spent, inline=False)
    recipient_embed.set_footer(text=f"Tip received from {interaction.user.display_name}", icon_url=interaction.user.avatar.url)
    recipient_embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    # Send the tip message publicly
    await interaction.response.send_message(tip_message)

    # Send updated wallets in the channel
    await interaction.channel.send(embed=sender_embed)
    await interaction.channel.send(embed=recipient_embed)

    # Send DM to sender with embed & tip message
    try:
        await interaction.user.send(f"✅ You sent **{value:,}M** as a tip to {user.mention}!", embed=sender_embed)
    except discord.Forbidden:
        await interaction.channel.send(f"⚠️ {interaction.user.mention}, I couldn't DM your updated wallet!")

    # Send DM to recipient with embed & received message
    try:
        await user.send(f"🎉 You received **{value:,}M** as a tip from {interaction.user.mention}!", embed=recipient_embed)
    except discord.Forbidden:
        await interaction.channel.send(f"⚠️ {user.mention}, I couldn't DM your updated wallet!")

class OrderButton(View):
    def __init__(self, order_id, deposit_required, customer_id, original_channel_id, message_id, post_channel_id):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.deposit_required = deposit_required
        self.customer_id = customer_id
        self.original_channel_id = original_channel_id
        self.message_id = message_id
        self.post_channel_id = post_channel_id

    @discord.ui.button(label="Apply For The Job✅", style=discord.ButtonStyle.primary)
    async def accept_job(self, interaction: Interaction, button: discord.ui.Button):
        order = orders_collection.find_one({"_id": self.order_id})
        if not order:
            await interaction.response.send_message("Order not found!", ephemeral=True)
            return

        if order.get("worker"):
            await interaction.response.send_message("This order has already been claimed!", ephemeral=True)
            return

        user_wallet = get_wallet(str(interaction.user.id))
        if user_wallet.get("deposit", 0) < self.deposit_required:
            await interaction.response.send_message("You do not have enough deposit to claim this order!", ephemeral=True)
            return

        # ✅ Send application notification and store the message object
        bot_spam_channel = bot.get_channel(1345349082608041996)
        if bot_spam_channel:
            embed = discord.Embed(title="📌 Job Application Received", color=discord.Color.from_rgb(139, 0, 0))
            embed.add_field(name="👷 Applicant", value=interaction.user.mention, inline=True)
            embed.add_field(name="🆔 Order ID", value=str(self.order_id), inline=True)
            embed.set_footer(text="Choose to Accept or Reject the applicant.")

            # ✅ Store the message object
            message_obj = await bot_spam_channel.send(embed=embed)

            # ✅ Pass message_obj to ApplicationView
            application_view = ApplicationView(
                self.order_id, interaction.user.id, self.customer_id,
                self.original_channel_id, self.message_id, self.post_channel_id,
                self.deposit_required, message_obj
            )
            await message_obj.edit(view=application_view)  # Attach the buttons

        await interaction.response.send_message("Your application has been submitted for review!", ephemeral=True)

class ApplicationView(View):
    def __init__(self, order_id, applicant_id, customer_id, original_channel_id, message_id, post_channel_id, deposit_required, message_obj):
        super().__init__(timeout=None)
        self.order_id = order_id
        self.applicant_id = applicant_id  # ✅ This is the worker
        self.customer_id = customer_id
        self.original_channel_id = original_channel_id
        self.message_id = message_id
        self.post_channel_id = post_channel_id
        self.deposit_required = deposit_required  
        self.message_obj = message_obj  # Store the applicant's message object

    @discord.ui.button(label="✅ Accept", style=discord.ButtonStyle.success)
    async def accept_applicant(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer()

        # ✅ Fetch order from database
        order = orders_collection.find_one({"_id": self.order_id})
        if not order:
            await interaction.followup.send("Order not found!", ephemeral=True)
            return

        if order.get("worker"):
            await interaction.followup.send("This order has already been claimed!", ephemeral=True)
            return

        # ✅ Assign worker in the database
        orders_collection.update_one({"_id": self.order_id}, {"$set": {"worker": self.applicant_id}})

        # ✅ Retrieve actual values for the embed
        description = order.get("description", "No description provided.")
        value = order.get("value", "N/A")
        deposit_required = order.get("deposit_required", "N/A")

        # ✅ Grant worker access to the original order channel
        original_channel = bot.get_channel(self.original_channel_id)
        if original_channel:
            worker = interaction.guild.get_member(self.applicant_id)
            if worker:
                await original_channel.set_permissions(worker, read_messages=True, send_messages=True)
            else:
                await interaction.followup.send("❌ Could not find the applicant in the server!", ephemeral=True)
                return

            # ✅ Corrected embed with actual order details
            embed = discord.Embed(title="🎡 Order Claimed", color=discord.Color.from_rgb(139, 0, 0))
            embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")
            embed.set_author(name="✅ Cynx System ✅", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")
            embed.add_field(name="📕 Description", value=description, inline=False)
            embed.add_field(name="👷 Worker", value=f"<@{self.applicant_id}>", inline=True)
            embed.add_field(name="📌 Customer", value=f"<@{self.customer_id}>", inline=True)
            embed.add_field(name="💵 Deposit Required", value=f"**```{deposit_required}M```**", inline=True)
            embed.add_field(name="💰 Order Value", value=f"**```{value}M```**", inline=True)
            embed.add_field(name="🆔 Order ID", value=self.order_id, inline=True)
            embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")
            embed.set_footer(text="Cynx System", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")
            sent_message = await original_channel.send(embed=embed)
            await sent_message.pin()

            # ✅ Notify customer and worker
            claim_message = f"**Hello! <@{self.customer_id}>, <@{self.applicant_id}> is Assigned To Be Your Worker For This Job. You Can Provide Your Account Info Using This Command `!inf`**"
            await original_channel.send(claim_message)

        # ✅ Delete the original job post
        post_channel = bot.get_channel(self.post_channel_id)
        if post_channel:
            try:
                message = await post_channel.fetch_message(self.message_id)
                await message.delete()
            except:
                pass

        # ✅ Delete the applicant's message
        try:
            await self.message_obj.delete()
        except:
            pass

        await interaction.followup.send("Applicant accepted and added to the order channel!", ephemeral=True)

    @discord.ui.button(label="❌ Reject", style=discord.ButtonStyle.danger)
    async def reject_applicant(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        await interaction.followup.send(f"Applicant <@{self.applicant_id}> has been rejected.", ephemeral=True)

        # ✅ Delete the applicant's message
        try:
            await self.message_obj.delete()
        except:
            pass




@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")

    # Reload buttons for active orders
    for order in orders_collection.find({"worker": None}):  # Only for unclaimed orders
        channel = bot.get_channel(order["channel_id"])
        if channel:
            try:
                message = await channel.fetch_message(order["message_id"])
                view = OrderButton(order["_id"], order["deposit_required"], order["customer"], order["original_channel_id"], order["message_id"])
                await message.edit(view=view)
            except discord.NotFound:
                print(f"Order message {order['message_id']} not found, skipping.")
    
    print("Re-registered all active order buttons!")

def get_next_order_id():
    counter = counters_collection.find_one({"_id": "order_counter"})
    
    if not counter:
        # Initialize the counter to 46 if it does not exist
        counters_collection.insert_one({"_id": "order_counter", "seq": 46})
        return 46  # First order ID should be 46

    # Increment and return the next order ID
    counter = counters_collection.find_one_and_update(
        {"_id": "order_counter"},
        {"$inc": {"seq": 1}},  # Increment the existing counter
        return_document=ReturnDocument.AFTER
    )
    return counter["seq"]

@bot.tree.command(name="post", description="Post a new order.")
@app_commands.describe(
    customer="The customer for the order",
    value="The value of the order (in millions)",
    deposit_required="The deposit required for the order",
    holder="The holder of the order",
    channel="The channel to post the order (mention or ID)",
    description="Description of the order"
)
async def post(interaction: discord.Interaction, customer: discord.Member, value: int, deposit_required: int, holder: discord.Member, channel: discord.TextChannel, description: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    channel_id = channel.id
    order_id = get_next_order_id()
    post_channel_id = interaction.channel.id  # Store the channel where /post was used

    # Define role IDs
    role1_id = 1208792946401615901
    role2_id = 1208792946401615902

    # Check if roles exist in the guild
    role1 = discord.utils.get(interaction.guild.roles, id=role1_id)
    role2 = discord.utils.get(interaction.guild.roles, id=role2_id)

    # Determine which role to ping
    if role1:
        role_ping = role1.mention
    elif role2:
        role_ping = role2.mention
    else:
        role_ping = None  # No roles found, so no ping

    embed = discord.Embed(title="<:wolf:1261406634802941994> New Order <:wolf:1261406634802941994>", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    embed.set_author(name="💼 Order Posted", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    embed.add_field(name="📕 Description", value=description, inline=False)
    embed.add_field(name="💰 Value", value=f"**```{value}M```**", inline=True)
    embed.add_field(name="💵 Deposit Required", value=f"**```{deposit_required}M```**", inline=True)
    embed.add_field(name="🕵️‍♂️ Holder", value=holder.mention, inline=True)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    embed.set_footer(text=f"Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")

    channel_to_post = interaction.guild.get_channel(channel_id)
    if channel_to_post:
        # Send message with role ping if a role exists
        if role_ping:
            message = await channel_to_post.send(f"{role_ping}", embed=embed)
        else:
            message = await channel_to_post.send(embed=embed)

        # Add order button functionality
        await message.edit(view=OrderButton(order_id, deposit_required, customer.id, post_channel_id, message.id, channel_id))

        orders_collection.insert_one({
            "_id": order_id,
            "customer": customer.id,
            "worker": None,
            "value": value,
            "deposit_required": deposit_required,
            "holder": holder.id,
            "message_id": message.id,
            "channel_id": channel.id,
            "original_channel_id": post_channel_id,  # Store where /post was used
            "description": description
        })

        confirmation_embed = embed.copy()
        confirmation_embed.title = "Order Posted"
        await interaction.channel.send(embed=confirmation_embed)
        await interaction.response.send_message("Order posted successfully!", ephemeral=True)
        await log_command(interaction, "Order Posted", f"Customer: {customer.mention} (`{customer.id}`)\nValue: {value:,}M\nDeposit Required: {deposit_required:,}M\nHolder: {holder.mention} (`{holder.id}`)\nChannel: {channel.mention}\nDescription: {description}")
    else:
        await interaction.response.send_message("Invalid channel specified.", ephemeral=True)

@bot.tree.command(name="set", description="Set an order directly with worker.")
async def set_order(interaction: Interaction, customer: discord.Member, value: int, deposit_required: int, holder: discord.Member, description: str, worker: discord.Member):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    order_id = get_next_order_id()  # Get a unique order ID
    original_channel_id = interaction.channel.id  # Save the original posting channel
    
    embed = Embed(title="Order Set", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    embed.set_author(name="🛠️ Order Set", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    embed.add_field(name="📕 Description", value=description, inline=False)
    embed.add_field(name="📌 Customer", value=customer.mention, inline=True)
    embed.add_field(name="🤑 Value", value=f"**```{value}M```**", inline=True)
    embed.add_field(name="💵 Deposit Required", value=f"**```{deposit_required}M```**", inline=True)
    embed.add_field(name="🕵️‍♂️ Holder", value=holder.mention, inline=True)
    embed.add_field(name="👷 Worker", value=worker.mention, inline=True)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    embed.set_footer(text=f"Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    
    # Send the order to the channel where the command was used
    original_channel = bot.get_channel(original_channel_id)
    if original_channel:
        message = await original_channel.send(embed=embed)  # Send the message to the original channel
        message_id = message.id  # Retrieve the message ID
    
    # Store order in the database, including the original channel where the order was posted
    orders_collection.insert_one({
        "_id": order_id,  # Use unique order ID
        "customer": customer.id,
        "worker": worker.id,  # Directly assign worker
        "value": value,
        "deposit_required": deposit_required,
        "holder": holder.id,
        "message_id": message_id,
        "channel_id": original_channel.id,  # Store the original channel ID
        "original_channel_id": original_channel_id,  # Store the original channel ID
        "description": description
    })

    # Notify the user that the order was successfully set
    await interaction.response.send_message(f"Order set with Worker {worker.mention}!", ephemeral=True)
    await log_command(interaction, "Order Set", f"Customer: {customer.mention} (`{customer.id}`)\nWorker: {worker.mention} (`{worker.id}`)\nValue: {value:,}M\nDeposit Required: {deposit_required:,}M\nHolder: {holder.mention} (`{holder.id}`)\nDescription: {description}")

    # Now, add the worker to the original channel and grant permissions
    if original_channel:
        try:
            # Add the worker to the channel, allowing them to read and send messages
            await original_channel.set_permissions(worker, read_messages=True, send_messages=True)
            print(f"Permissions granted to {worker.name} in {original_channel.name}.")
        except Exception as e:
            print(f"Failed to set permissions for {worker.name} in {original_channel.name}: {e}")
# /complete command
@bot.tree.command(name="complete", description="Mark an order as completed.")
async def complete(interaction: Interaction, order_id: int):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    
    order = orders_collection.find_one({"_id": order_id})
    if not order:
        await interaction.response.send_message("Order not found!", ephemeral=True)
        return
    
    # Removed the worker check to allow permission roles to complete orders
    # Now, as long as the user has permission, they can mark the order as completed

    # Transfer funds
    update_wallet(str(order["customer"]), "spent", order["value"])
    worker_payment = round(order["value"] * 0.85, 1)  # Keeps one decimal place
    update_wallet(str(order["worker"]), "wallet", float(worker_payment))  # Ensure it's stored as float
    orders_collection.update_one({"_id": order_id}, {"$set": {"status": "completed"}})
    
    # Notify the original channel
    original_channel = bot.get_channel(order["original_channel_id"])
    if original_channel:
        embed = Embed(title="✅ Order Completed", color=discord.Color.from_rgb(139, 0, 0))
        embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
        embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
        embed.add_field(name="📕 Description", value=order.get("description", "No description provided."), inline=False)
        embed.add_field(name="👷 Worker", value=f"<@{order['worker']}>", inline=True)
        embed.add_field(name="📌 Customer", value=f"<@{order['customer']}>", inline=True)
        embed.add_field(name="🤑 Value", value=f"**```{order['value']}M```**", inline=True)
        embed.add_field(name="👷‍♂️ Worker Payment", value=f"**```{worker_payment}M```**", inline=True)
        embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
        embed.set_footer(text=f"Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
        await original_channel.send(embed=embed)
    
    # DM the worker
    worker = bot.get_user(order["worker"])
    if worker:
        dm_embed = Embed(title="✅ Order Completed", color=discord.Color.from_rgb(139, 0, 0))
        dm_embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
        dm_embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
        dm_embed.add_field(name="📕 Description", value=order.get("description", "No description provided."), inline=False)
        dm_embed.add_field(name="📌 Customer", value=f"<@{order['customer']}>", inline=True)
        dm_embed.add_field(name="🤑 Value", value=f"**```{order['value']}M```**", inline=True)
        dm_embed.add_field(name="👷‍♂️ Your Payment", value=f"**```{worker_payment}M```**", inline=True)
        dm_embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
        dm_embed.set_footer(text=f"Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
        await worker.send(embed=dm_embed)
    
    await interaction.response.send_message("Order marked as completed!", ephemeral=True)
    await log_command(interaction, "Order Completed", f"Order ID: {order_id}\nMarked by: {interaction.user.mention} (`{interaction.user.id}`)\nWorker: <@{order['worker']}> (`{order['worker']}`)\nCustomer: <@{order['customer']}> (`{order['customer']}`)\nValue: {order['value']}M\nWorker Payment: {worker_payment}M")

# 📌 /order_deletion command
@bot.tree.command(name="order_deletion", description="Delete an order.")
async def order_deletion(interaction: Interaction, order_id: int):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return
    order = orders_collection.find_one({"_id": order_id})
    
    if not order:
        await interaction.response.send_message("❌ Order not found!", ephemeral=True)
        return

    # Delete the order message in the orders channel
    order_channel = bot.get_channel(order["channel_id"])
    if order_channel:
        try:
            message = await order_channel.fetch_message(order["message_id"])
            await message.delete()
        except discord.NotFound:
            print(f"⚠️ Message for order {order_id} not found in orders channel. Skipping deletion.")

    # Delete the original post message in the interaction channel
    original_channel = bot.get_channel(order["original_channel_id"])
    if original_channel:
        try:
            original_message = await original_channel.fetch_message(order["message_id"])
            await original_message.delete()
        except discord.NotFound:
            print(f"⚠️ Original message for order {order_id} not found. Skipping deletion.")

    # Remove the order from MongoDB
    orders_collection.delete_one({"_id": order_id})
    
    await interaction.response.send_message(f"✅ Order {order_id} has been successfully deleted.", ephemeral=True)
    await log_command(interaction, "Order Deleted", f"Order ID: {order_id}\nDeleted by: {interaction.user.mention} (`{interaction.user.id}`)")

@bot.tree.command(name="view_order", description="View details of an order")
async def view_order(interaction: discord.Interaction, order_id: int):
    # Required role IDs
    allowed_roles = {1208792946401615900, 1208792946430836736, 1211406868480532571}

    # Check if user has at least one of the required roles
    if not any(role.id in allowed_roles for role in interaction.user.roles):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return

    order = orders_collection.find_one({"_id": order_id})
    
    if not order:
        await interaction.response.send_message("❌ Order not found.", ephemeral=True)
        return

    # Extract values safely, handling possible None values
    worker_id = order.get("worker", {}).get("low") if isinstance(order.get("worker"), dict) else order.get("worker", "Not Assigned")
    customer_id = order.get("customer", {}).get("low") if isinstance(order.get("customer"), dict) else order.get("customer", "Unknown")
    holder_id = order.get("holder", {}).get("low") if isinstance(order.get("holder"), dict) else order.get("holder", "N/A")
    
    deposit = order.get("deposit_required", 0)
    value = order.get("value", 0)
    description = order.get("description", "No description provided")

    # Get status, default to "In Progress"
    status = order.get("status", "In Progress").capitalize()

    embed = discord.Embed(title="📦 Order Details", color=discord.Color.from_rgb(139, 0, 0))
    embed.add_field(name="📊 Status", value=status, inline=False)
    embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    embed.add_field(name="👷 Worker", value=f"<@{worker_id}>" if isinstance(worker_id, int) else worker_id, inline=False)
    embed.add_field(name="📌 Customer", value=f"<@{customer_id}>" if isinstance(customer_id, int) else customer_id, inline=False)
    embed.add_field(name="🎟️ Holder", value=f"<@{holder_id}>" if isinstance(holder_id, int) else holder_id, inline=False)
    embed.add_field(name="📕 Description", value=description, inline=False)
    embed.add_field(name="💵 Deposit", value=f"**```{deposit}M```**", inline=True)
    embed.add_field(name="💰 Order Value", value=f"**```{value}M```**", inline=True)
    embed.add_field(name="🆔 Order ID", value=order_id, inline=False)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&=")
    await interaction.response.send_message(embed=embed)



# Syncing command tree for slash commands
@bot.event
async def on_ready():
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} (ID: {bot.user.id})")
    try:
        synced = await bot.tree.sync()  # Sync all slash commands
        print(f"Synced {len(synced)} commands.")
    except Exception as e:
        print(f"Error syncing commands: {e}")

# Flask setup for keeping the bot alive (Replit hosting)
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    thread = Thread(target=run)
    thread.start()

# Add restart command for the bot (Owner-only)
@bot.command()
@commands.is_owner()
async def restart(ctx):
    await ctx.send("Restarting bot...")
    os.execv(__file__, ['python'] + os.sys.argv)

# Retrieve the token from the environment variable
token = os.getenv('DISCORD_BOT_TOKEN')
if not token:
    print("Error: DISCORD_BOT_TOKEN is not set in the environment variables.")
    exit(1)

# Keep the bot alive for Replit hosting
keep_alive()

@bot.command()
async def test(ctx):
    await ctx.send("Bot is responding!")

@bot.command()
async def ping(ctx):
    await ctx.send("Pong!")
# Run the bot with the token
bot.run(token)
