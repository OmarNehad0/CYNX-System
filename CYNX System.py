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
from collections import defaultdict
logging.basicConfig(level=logging.INFO)

bumper_task = None  # Ensure bumper_task is globally defined

# Set up intents
intents = discord.Intents.default()
intents.members = True  # For member join tracking
intents.message_content = True  # Required for prefix commands

bot = commands.Bot(command_prefix="!", intents=intents)


# In-memory RSN tracking
subscriptions = defaultdict(set)
# Key: RSN (lowercase), Value: Set of channel IDs
rsn_subscriptions = defaultdict(set)
# Replace this with your actual Dink webhook channel ID
DINK_CHANNEL_ID = 1374820955330969691  # <-- REPLACE THIS

# ==== Slash Commands ====

@bot.tree.command(name="track_rsn", description="Subscribe this channel to a specific RSN.")
@app_commands.describe(rsn="The RSN to track.")
async def track_rsn(interaction: discord.Interaction, rsn: str):
    rsn_key = rsn.lower()
    channel_id = interaction.channel_id
    rsn_subscriptions[rsn_key].add(channel_id)
    await interaction.response.send_message(f"✅ This channel is now tracking RSN: `{rsn}`.", ephemeral=True)

@bot.tree.command(name="untrack_rsn", description="Unsubscribe this channel from a specific RSN.")
@app_commands.describe(rsn="The RSN to stop tracking.")
async def untrack_rsn(interaction: discord.Interaction, rsn: str):
    rsn_key = rsn.lower()
    channel_id = interaction.channel_id
    if channel_id in rsn_subscriptions.get(rsn_key, set()):
        rsn_subscriptions[rsn_key].remove(channel_id)
        await interaction.response.send_message(f"🛑 This channel has stopped tracking RSN: `{rsn}`.", ephemeral=True)
    else:
        await interaction.response.send_message(f"⚠️ This channel was not tracking RSN: `{rsn}`.", ephemeral=True)

@bot.tree.command(name="list_tracked_rsns", description="List all RSNs this channel is tracking.")
async def list_tracked_rsns(interaction: discord.Interaction):
    channel_id = interaction.channel_id
    tracked = [rsn for rsn, channels in rsn_subscriptions.items() if channel_id in channels]
    if tracked:
        rsn_list = ', '.join(tracked)
        await interaction.response.send_message(f"📄 This channel is tracking the following RSNs: {rsn_list}", ephemeral=True)
    else:
        await interaction.response.send_message("📄 This channel is not tracking any RSNs.", ephemeral=True)

@bot.event
async def on_message(message: discord.Message):
    await bot.process_commands(message)  # Ensure commands still work

    # Replace with your actual Dink channel ID
    DINK_CHANNEL_ID = 1374820955330969691

    if message.channel.id != DINK_CHANNEL_ID:
        return

    # Ignore messages from bots that are not webhooks
    if message.author.bot and message.webhook_id is None:
        return

    # Compile the message content and embed texts
    content = (message.content or "").lower()
    for embed in message.embeds:
        if embed.title:
            content += f" {embed.title.lower()}"
        if embed.description:
            content += f" {embed.description.lower()}"
        if embed.footer and embed.footer.text:
            content += f" {embed.footer.text.lower()}"
        if embed.author and embed.author.name:
            content += f" {embed.author.name.lower()}"
        for field in embed.fields:
            content += f" {field.name.lower()} {field.value.lower()}"

    # Check for RSN matches and forward messages
    for rsn, channels in rsn_subscriptions.items():
        if rsn in content:
            for channel_id in channels:
                try:
                    target_channel = await bot.fetch_channel(channel_id)
                    if message.embeds:
                        for embed in message.embeds:
                            await target_channel.send(embed=embed)
                    if message.attachments:
                        for attachment in message.attachments:
                            if attachment.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
                                await target_channel.send(attachment.url)
                except Exception as e:
                    print(f"Error forwarding message to channel {channel_id}: {e}")
            break  # Stop after the first matching RSN


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

# Function to get wallet data (updated to handle both m and $)
def get_wallet(user_id):
    # Attempt to fetch the user's wallet data from MongoDB
    wallet_data = wallets_collection.find_one({"user_id": user_id})

    # If the wallet doesn't exist in the database, create a new one with default values
    if not wallet_data:
        print(f"Wallet not found for {user_id}, creating new wallet...")
        wallet_data = {
            "user_id": user_id,
            "wallet": 0,     # Initialize with 0M
            "wallet_dollars": 0,  # Initialize with 0$
            "spent": 0,      # Initialize with 0M spent
            "spent_dollars": 0,  # Initialize with 0$ spent
            "deposit": 0     # Initialize with 0M deposit
        }
        # Insert the new wallet into the database
        wallets_collection.insert_one(wallet_data)
        print(f"New wallet created for {user_id}: {wallet_data}")

    return wallet_data
# Function to update wallet in MongoDB
def update_wallet(user_id, field, value, currency):
    # Make sure the wallet document exists before updating
    wallet_data = get_wallet(user_id)

    # If the wallet does not contain the required field, we initialize it with the correct value
    if currency == "m" and field not in wallet_data:
        wallet_data[field] = 0  # Initialize the field if missing (for millions of gold)
    elif currency == "$" and field not in wallet_data:
        wallet_data[field] = 0  # Initialize the field if missing (for dollars)

    # Update wallet data by incrementing the field value based on currency
    if currency == "m":
        wallets_collection.update_one(
            {"user_id": user_id},
            {"$inc": {field: value}},  # Increment the field (e.g., wallet_m, deposit_m, spent_m)
            upsert=True  # Insert a new document if one doesn't exist
        )
    elif currency == "$":
        # Update the dollars field
        wallets_collection.update_one(
            {"user_id": user_id},
            {"$inc": {field: value}},  # Increment the dollars field (e.g., wallet_dollars, spent_dollars)
            upsert=True  # Insert a new document if one doesn't exist
        )

@bot.tree.command(name="wallet", description="Check a user's wallet balance")
async def wallet(interaction: discord.Interaction, user: discord.Member = None):
    # Define role IDs for special access (e.g., self-only role)
    self_only_roles = {1212728950606794763, 1208822252850909234} 
    allowed_roles = {1208792946430836736, 1208792946401615900, 1211406868480532571, 1208792946401615902}

    # Check if the user has permission
    user_roles = {role.id for role in interaction.user.roles}
    has_self_only_role = bool(self_only_roles & user_roles)  # User has at least one self-only role
    has_allowed_role = bool(allowed_roles & user_roles)  # User has at least one allowed role

    # If the user has no valid role, deny access
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
    wallet_dollars = wallet_data.get('wallet_dollars', 0)
    spent_dollars = wallet_data.get('spent_dollars', 0)
    deposit_dollars = wallet_data.get('deposit_dollars', 0)

    # Get user's avatar (fallback to default image)
    default_thumbnail = "https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif?ex=67bee1db&is=67bd905b&hm=2969ccb9dc0950d378d7a07d8baffccd674edffd7daea2059117e0a3b814a0b6&="
    thumbnail_url = user.avatar.url if user.avatar else default_thumbnail
    

    # Create embed message
    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=thumbnail_url)
    embed.add_field(
        name="<:200pxBlood_money_detail:1210284746966306846> Wallet",
        value=f"```🤑 {wallet_value}M | ${wallet_dollars}```",
        inline=False
    )
    embed.add_field(
    name="<:70023pepepresident:1321482641475637349> Deposit",
    value=f"```💵 {deposit_value}M | ${deposit_dollars}```",
    inline=False
    )
    embed.add_field(
        name="<:wolf:1261406634802941994> Spent",
        value=f"```🎃 {spent_value}M | ${spent_dollars}```",
        inline=False
    )
    # Only show commission wallet for these two owners
    owner_ids = {"944654043878400120", "617160222573592589"}
    if user_id in owner_ids:
        commission_dollars = wallet_data.get('commission_dollars', 0)
        embed.add_field(
            name="🏦 Commission Wallet",
            value=f"💼 ${commission_dollars}",
            inline=False
        )
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")

    # Ensure requester avatar exists
    requester_avatar = interaction.user.avatar.url if interaction.user.avatar else default_thumbnail
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=requester_avatar)

    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="add_remove_spent", description="Add or remove spent value from a user's wallet")
@app_commands.choices(
    action=[
        discord.app_commands.Choice(name="Add", value="add"),
        discord.app_commands.Choice(name="Remove", value="remove")
    ],
    currency=[
        discord.app_commands.Choice(name="M (millions of gold)", value="m"),
        discord.app_commands.Choice(name="$ (dollars)", value="$")
    ]
)
async def add_remove_spent(
    interaction: discord.Interaction,
    user: discord.Member,
    action: str,
    currency: str,
    value: float
):
    if not has_permission(interaction.user):  # Check role permissions
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(user.id)

    # Determine field name based on currency
    field_name = 'spent_dollars' if currency == '$' else 'spent'

    # Fetch current wallet data
    wallet_data = get_wallet(user_id)
    spent_value = wallet_data.get(field_name, 0)

    if action == "remove":
        if spent_value < value:
            await interaction.response.send_message("⚠ Insufficient spent balance to remove!", ephemeral=True)
            return
        update_wallet(user_id, field_name, -value, currency)
    else:
        update_wallet(user_id, field_name, value, currency)

    # Fetch updated wallet data
    updated_wallet = get_wallet(user_id)
    spent_m = updated_wallet.get("spent", 0)
    spent_dollars = updated_wallet.get("spent_dollars", 0)

    # Assign roles only for M currency
    if currency == "$":
        display_value = f"${spent_dollars}"
        field_name_display = "<:wolf:1261406634802941994> Spent ($)"
    else:
        display_value = f"🎃 {spent_m}M"
        field_name_display = "<:wolf:1261406634802941994> Spent (M)"

    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
    embed.add_field(name=field_name_display, value=f"```{display_value}```", inline=False)
    embed.set_footer(text=f"Updated by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)

    await interaction.response.send_message(f"✅ {action.capitalize()} {value}{currency} spent.", embed=embed)
    await log_command(interaction, "add_remove_spent", f"User: {user.mention} | Action: {action} | Value: {value}{currency}")
    await check_and_assign_roles(user, spent_m, spent_dollars, interaction.client)

async def check_and_assign_roles(user: discord.Member, spent_m: float, spent_dollars: float, client):
    """
    Converts $ to M (1$ = 5M) and assigns roles based on total spent.
    """
    role_milestones = {
        1: 1212554296294514768,      # 1M+
        4000: 1210262407994413176,   # 4M+
        5000: 1210262187638132806,   # 5M+
        7000: 1210090197845282908,   # 7M+
        9000: 1210088939919118336,   # 9M+
        14000: 1209962980179968010   # 14M+
    }

    total_spent_in_m = spent_m + (spent_dollars * 5)

    congrats_channel = client.get_channel(1210687108457701468)
    if congrats_channel is None:
        try:
            congrats_channel = await client.fetch_channel(1210687108457701468)
        except Exception as e:
            print(f"[ERROR] Could not fetch congrats channel: {e}")
            return

    print(f"[DEBUG] {user.display_name} - Total Spent: {total_spent_in_m}M")

    for threshold, role_id in sorted(role_milestones.items()):
        role = user.guild.get_role(role_id)
        if not role:
            print(f"[ERROR] Role ID {role_id} not found!")
            continue

        if total_spent_in_m >= threshold and role not in user.roles:
            await user.add_roles(role)

            embed = discord.Embed(
                title="🎉 Congratulations!",
                description=f"{user.mention} has reached **{threshold:,}M+** spent and earned a new role!",
                color=discord.Color.gold()
            )
            embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)
            embed.add_field(name="🏅 New Role Earned:", value=role.mention, inline=False)
            embed.set_footer(
                text="Keep spending to reach new Lifetime Rank! ✨",
                icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif"
            )
            embed.set_author(
                name="✅ Cynx System ✅",
                icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif"
            )

            await congrats_channel.send(embed=embed)


@bot.tree.command(name="wallet_add_remove", description="Add or remove value from a user's wallet (M or $)")
@app_commands.choices(
    action=[
        discord.app_commands.Choice(name="Add", value="add"),
        discord.app_commands.Choice(name="Remove", value="remove")
    ],
    currency=[
        discord.app_commands.Choice(name="M (OSRS GP)", value="m"),
        discord.app_commands.Choice(name="$ (USD)", value="$")
    ]
)
async def wallet_add_remove(
    interaction: discord.Interaction,
    user: discord.Member,
    action: str,
    value: float,
    currency: str
):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(user.id)
    wallet_data = get_wallet(user_id)

    wallet_key = "wallet" if currency == "m" else "wallet_dollars"
    current_wallet = wallet_data.get(wallet_key, 0)

    if action == "remove":
        if current_wallet < value:
            await interaction.response.send_message(f"⚠ Insufficient balance to remove {value}{currency}!", ephemeral=True)
            return
        update_wallet(user_id, wallet_key, -value, currency)
    else:
        update_wallet(user_id, wallet_key, value, currency)

    # Refresh data after update
    updated = get_wallet(user_id)

    deposit_value = updated.get("deposit", 0)
    wallet_value = updated.get("wallet", 0)
    wallet_dollars = updated.get("wallet_dollars", 0)
    spent_value = updated.get("spent", 0)
    spent_dollars = updated.get("spent_dollars", 0)

    embed = discord.Embed(
        title=f"{user.display_name}'s Wallet 💳",
        color=discord.Color.from_rgb(139, 0, 0)
    )
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)

    embed.add_field(
        name="<:70023pepepresident:1321482641475637349> Deposit",
        value=f"```💵 {deposit_value:,}M```",
        inline=False
    )
    embed.add_field(
        name="<:200pxBlood_money_detail:1210284746966306846> Wallet",
        value=f"```🤑 {wallet_value:,}M | ${wallet_dollars:,}```",
        inline=False
    )
    embed.add_field(
        name="<:wolf:1261406634802941994> Spent",
        value=f"```🎃 {spent_value:,}M | ${spent_dollars:,}```",
        inline=False
    )
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)

    await interaction.response.send_message(
        f"✅ {action.capitalize()}ed {value:,}{currency}.",
        embed=embed
    )
    await log_command(interaction, "wallet_add_remove", f"User: {user.mention} | Action: {action} | Value: {value:,}{currency}")



@bot.tree.command(name="deposit", description="Set or remove a user's deposit value")
@app_commands.choices(action=[
    discord.app_commands.Choice(name="Set", value="set"),
    discord.app_commands.Choice(name="Remove", value="remove")
])
@app_commands.describe(currency="Currency type (m or $)")
async def deposit(interaction: discord.Interaction, user: discord.Member, action: str, value: int, currency: str):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(user.id)
    wallet_data = get_wallet(user_id)

    deposit_key = "deposit" if currency == "m" else "deposit_dollars"
    wallet_key = "wallet" if currency == "m" else "wallet_dollars"
    spent_key = "spent" if currency == "m" else "spent_dollars"
    symbol = "M" if currency == "m" else "$"

    current_deposit = wallet_data.get(deposit_key, 0)

    if action == "set":
        new_deposit = current_deposit + value
    elif action == "remove":
        if value > current_deposit:
            await interaction.response.send_message(
                f"⚠ Cannot remove {value}{symbol}. The user only has {current_deposit}{symbol} in deposit.",
                ephemeral=True
            )
            return
        new_deposit = current_deposit - value

    # Update MongoDB
    update_wallet(user_id, deposit_key, new_deposit - current_deposit, currency)

    updated_wallet = get_wallet(user_id)

    # Current deposit display
    deposit_value = f"```💵 {updated_wallet.get(deposit_key, 0):,}{symbol}```"

    # Get all values for M and $
    wallet_m = f"{updated_wallet.get('wallet', 0):,}"
    wallet_dollars = f"{updated_wallet.get('wallet_dollars', 0):,}"
    spent_m = f"{updated_wallet.get('spent', 0):,}"
    spent_dollars = f"{updated_wallet.get('spent_dollars', 0):,}"

    embed = discord.Embed(title=f"{user.display_name}'s Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url=user.avatar.url if user.avatar else user.default_avatar.url)

    embed.add_field(name="<:70023pepepresident:1321482641475637349> Deposit", value=deposit_value, inline=False)
    embed.add_field(
        name="<:200pxBlood_money_detail:1210284746966306846> Wallet",
        value=f"```🤑 {wallet_m}M | ${wallet_dollars}```",
        inline=False
    )
    embed.add_field(
        name="<:wolf:1261406634802941994> Spent",
        value=f"```🎃 {spent_m}M | ${spent_dollars}```",
        inline=False
    )

    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")

    await interaction.response.send_message(
        f"✅ {action.capitalize()}ed deposit value for {user.name} by {value:,}{symbol}.",
        embed=embed
    )

    await log_command(
        interaction,
        "Deposit Set/Remove",
        f"User: {user.mention} (`{user.id}`)\nAction: {action.capitalize()}\nAmount: {value:,}{symbol}"
    )



@bot.tree.command(name="tip", description="Tip M or $ to another user.")
@app_commands.describe(user="User to tip", value="Amount to tip", currency="Currency type: m or $")
async def tip(interaction: discord.Interaction, user: discord.Member, value: int, currency: str):
    sender_id = str(interaction.user.id)
    recipient_id = str(user.id)

    symbol = "M" if currency == "m" else "$"
    wallet_key = "wallet" if currency == "m" else "wallet_dollars"

    sender_wallet = get_wallet(sender_id)
    recipient_wallet = get_wallet(recipient_id)

    if sender_wallet.get(wallet_key, 0) < value:
        await interaction.response.send_message(f"❌ You don't have enough {symbol} to tip!", ephemeral=True)
        return

    # Update wallets
    update_wallet(sender_id, wallet_key, -value, currency)
    update_wallet(recipient_id, wallet_key, value, currency)

    # Refresh data
    sender_wallet = get_wallet(sender_id)
    recipient_wallet = get_wallet(recipient_id)

    # Sender Embed
    embed_sender = discord.Embed(title=f"{interaction.user.display_name}'s Updated Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed_sender.set_thumbnail(url=interaction.user.avatar.url)
    embed_sender.add_field(
        name="<:200pxBlood_money_detail:1210284746966306846> Wallet",
        value=f"```🤑 {sender_wallet.get('wallet', 0):,}M | ${sender_wallet.get('wallet_dollars', 0):,}```",
        inline=False
    )
    embed_sender.add_field(
        name="<:70023pepepresident:1321482641475637349> Deposit",
        value=f"```💵 {sender_wallet.get('deposit', 0):,}M```",
        inline=False
    )
    embed_sender.add_field(
        name="<:wolf:1261406634802941994> Spent",
        value=f"```🎃 {sender_wallet.get('spent', 0):,}M | ${sender_wallet.get('spent_dollars', 0):,}```",
        inline=False
    )
    embed_sender.set_footer(text=f"Tip sent to {user.display_name}", icon_url=user.avatar.url)
    embed_sender.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")

    # Recipient Embed
    embed_recipient = discord.Embed(title=f"{user.display_name}'s Updated Wallet 💳", color=discord.Color.from_rgb(139, 0, 0))
    embed_recipient.set_thumbnail(url=user.avatar.url)
    embed_recipient.add_field(
        name="<:200pxBlood_money_detail:1210284746966306846> Wallet",
        value=f"```🤑 {recipient_wallet.get('wallet', 0):,}M | ${recipient_wallet.get('wallet_dollars', 0):,}```",
        inline=False
    )
    embed_recipient.add_field(
        name="<:70023pepepresident:1321482641475637349> Deposit",
        value=f"```💵 {recipient_wallet.get('deposit', 0):,}M```",
        inline=False
    )
    embed_recipient.add_field(
        name="<:wolf:1261406634802941994> Spent",
        value=f"```🎃 {recipient_wallet.get('spent', 0):,}M | ${recipient_wallet.get('spent_dollars', 0):,}```",
        inline=False
    )
    embed_recipient.set_footer(text=f"Tip received from {interaction.user.display_name}", icon_url=interaction.user.avatar.url)
    embed_recipient.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")

    # Channel message
    await interaction.response.send_message(f"💸 {interaction.user.mention} tipped {user.mention} **{value:,}{symbol}**!")
    await interaction.channel.send(embed=embed_sender)
    await interaction.channel.send(embed=embed_recipient)

    # DM both users, catch error if DMs are turned off
    try:
        await interaction.user.send(f"✅ You tipped **{value:,}{symbol}** to {user.display_name}!", embed=embed_sender)
    except discord.Forbidden:
        pass  # No DM sent, so we just pass

    try:
        await user.send(f"🎉 You received **{value:,}{symbol}** as a tip from {interaction.user.display_name}!", embed=embed_recipient)
    except discord.Forbidden:
        pass  # No DM sent, so we just pass

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
        if user_wallet.get("deposit_dollars", 0) < self.deposit_required:
            await interaction.response.send_message("You do not have enough $ deposit to claim this order!", ephemeral=True)
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
            embed = discord.Embed(title="👷‍♂️ Order Claimed", color=discord.Color.from_rgb(139, 0, 0))
            embed.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&=")
            embed.set_author(name="✅ Cynx System ✅", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&=")
            embed.add_field(name="📕 Description", value=description, inline=False)
            embed.add_field(name="👷 Worker", value=f"<@{self.applicant_id}>", inline=True)
            embed.add_field(name="📌 Customer", value=f"<@{self.customer_id}>", inline=True)
            embed.add_field(name="💵 Deposit Required", value=f"**```{deposit_required}$```**", inline=True)
            embed.add_field(name="💰 Order Value", value=f"**```{value}$```**", inline=True)
            embed.add_field(name="🆔 Order ID", value=self.order_id, inline=True)
            embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")
            embed.set_footer(text="Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&=")
            sent_message = await original_channel.send(embed=embed)
            await sent_message.pin()

            # ✅ Notify customer and worker
            claim_message = f"**Hello! <@{self.customer_id}>, <@{self.applicant_id}> is Assigned To Be Your Worker For This Job. You Can Provide Your Account Info Using This Command `/inf`**"
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
                view = OrderButton(order["_id"], order["deposit_required"], order["customer"], order["original_channel_id"], order["message_id"], order["post_channel_id"])
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
    description="Description of the order",
    image="Image URL to show at the bottom of the embed"
)
async def post(
    interaction: discord.Interaction,
    customer: discord.Member,
    value: float,
    deposit_required: float,
    holder: discord.Member,
    channel: discord.TextChannel,
    description: str,
    image: str = None
):
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

    # Create embed for the order post
    embed = discord.Embed(
        title="<:wolf:1261406634802941994> New Order <:wolf:1261406634802941994>",
        color=discord.Color.from_rgb(139, 0, 0)
    )
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&=")
    embed.set_author(
        name="💼 Order Posted",
        icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&="
    )
    embed.description = f"📕 **Description:**\n{description}"
    embed.add_field(name="💰 Value", value=f"**```${value:,.2f}```**", inline=True)
    embed.add_field(name="💵 Deposit Required", value=f"**```${deposit_required:,.2f}```**", inline=True)
    embed.add_field(name="🕵️‍♂️ Holder", value=holder.mention, inline=True)

    # Add image
    if image:
        embed.set_image(url=image)
    else:
        embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")

    embed.set_footer(
        text=f"Order ID: {order_id}",
        icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&="
    )

    channel_to_post = interaction.guild.get_channel(channel_id)
    if channel_to_post:
        # Send message with role ping if available
        if role_ping:
            message = await channel_to_post.send(f"{role_ping}", embed=embed)
        else:
            message = await channel_to_post.send(embed=embed)

        # Add claim button
        await message.edit(
            view=OrderButton(order_id, deposit_required, customer.id, post_channel_id, message.id, channel_id)
        )

        # Insert order data into database
        orders_collection.insert_one({
            "_id": order_id,
            "customer": customer.id,
            "worker": None,
            "value": value,
            "deposit_required": deposit_required,
            "holder": holder.id,
            "message_id": message.id,
            "channel_id": channel.id,
            "original_channel_id": post_channel_id,
            "description": description,
            "currency": "$",
            "posted_by": interaction.user.id  # ✅ added this
        })

        # Confirmation message
        confirmation_embed = embed.copy()
        confirmation_embed.title = "✅ Order Posted Successfully"
        await interaction.channel.send(embed=confirmation_embed)

        await interaction.response.send_message("💵 Order posted successfully in USD!", ephemeral=True)

        # Log the command
        await log_command(
            interaction,
            "Order Posted",
            f"Customer: {customer.mention} (`{customer.id}`)\n"
            f"Value: ${value:,.2f}\n"
            f"Deposit Required: ${deposit_required:,.2f}\n"
            f"Holder: {holder.mention} (`{holder.id}`)\n"
            f"Channel: {channel.mention}\n"
            f"Description: {description}"
        )
    else:
        await interaction.response.send_message("❌ Invalid channel specified.", ephemeral=True)


@bot.tree.command(name="set", description="Set an order directly with worker (USD only).")
async def set_order(
    interaction: Interaction,
    customer: discord.Member,
    value: int,
    deposit_required: int,
    holder: discord.Member,
    description: str,
    worker: discord.Member
):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    # العملة ثابتة بالدولار فقط
    currency_symbol = "$"

    # تنسيق الأرقام
    formatted_value = f"{value:,}{currency_symbol}"
    formatted_deposit = f"{deposit_required:,}{currency_symbol}"

    # إنشاء رقم الطلب
    order_id = get_next_order_id()
    original_channel_id = interaction.channel.id
    original_channel = bot.get_channel(original_channel_id)

    # التحقق من إيداع العامل
    wallet_data = get_wallet(str(worker.id))
    worker_deposit = wallet_data.get("deposit_dollars", 0)

    if worker_deposit < deposit_required:
        await interaction.response.send_message(
            f"⚠️ {worker.display_name} does not have enough deposit to take this job. "
            f"Required: {deposit_required}{currency_symbol}, Available: {worker_deposit}{currency_symbol}",
            ephemeral=True
        )
        return

    # إنشاء الإيمبد
    embed = Embed(title="Order Set", color=discord.Color.from_rgb(139, 0, 0))
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")
    embed.set_author(name="🛠️ Order Set", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")
    embed.add_field(name="📕 Description", value=description, inline=False)
    embed.add_field(name="📌 Customer", value=customer.mention, inline=True)
    embed.add_field(name="🤑 Value", value=f"**```{formatted_value}```**", inline=True)
    embed.add_field(name="💵 Deposit Required", value=f"**```{formatted_deposit}```**", inline=True)
    embed.add_field(name="🕵️‍♂️ Holder", value=holder.mention, inline=True)
    embed.add_field(name="👷 Worker", value=worker.mention, inline=True)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")
    embed.set_footer(text=f"Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/985890908027367474/1208891137910120458/Cynx_avatar.gif")

    # إرسال الإيمبد
    if original_channel:
        message = await original_channel.send(embed=embed)
        message_id = message.id
    else:
        await interaction.response.send_message("❌ Could not find the current channel.", ephemeral=True)
        return

    # حفظ الطلب في قاعدة البيانات
    orders_collection.insert_one({
        "_id": order_id,
        "customer": customer.id,
        "worker": worker.id,
        "value": value,
        "deposit_required": deposit_required,
        "holder": holder.id,
        "message_id": message_id,
        "channel_id": original_channel.id,
        "original_channel_id": original_channel_id,
        "description": description,
        "status": "in_progress",
        "currency": "$",
        "posted_by": interaction.user.id  # ✅ added this
    })

    # تحديث المحافظ بالدولار فقط
    update_wallet(str(customer.id), "spent_dollars", deposit_required, "$")
    update_wallet(str(worker.id), "wallet_dollars", round(deposit_required * 0.85, 2), "$")

    # تأكيد العملية
    await interaction.response.send_message(f"✅ Order set with Worker {worker.mention}!", ephemeral=True)

    await log_command(
        interaction,
        "Order Set",
        f"Customer: {customer.mention} (`{customer.id}`)\n"
        f"Worker: {worker.mention} (`{worker.id}`)\n"
        f"Value: {formatted_value}\n"
        f"Deposit Required: {formatted_deposit}\n"
        f"Holder: {holder.mention} (`{holder.id}`)\n"
        f"Description: {description}"
    )

    # السماح للعامل بالوصول إلى القناة
    try:
        await original_channel.set_permissions(worker, read_messages=True, send_messages=True)
        print(f"Permissions granted to {worker.name} in {original_channel.name}.")
    except Exception as e:
        print(f"Failed to set permissions for {worker.name} in {original_channel.name}: {e}")

# /complete command
# /complete command (USD ONLY VERSION)
@bot.tree.command(name="complete", description="Mark an order as completed (USD only).")
async def complete(interaction: Interaction, order_id: int):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    order = orders_collection.find_one({"_id": order_id})
    if not order:
        await interaction.response.send_message("❌ Order not found!", ephemeral=True)
        return

    if order.get("status") == "completed":
        await interaction.response.send_message("⚠️ This order has already been marked as completed.", ephemeral=True)
        return

    # Extract customer ID and worker ID
    customer_id = str(order["customer"])
    worker_id = str(order["worker"])

    # Transfer funds
    update_wallet(customer_id, "spent_dollars", order["value"], "$")

    total_value = order["value"]
    worker_payment = round(total_value * 0.80, 2)
    commission_total = round(total_value * 0.15, 2)
    helper_payment = round(total_value * 0.05, 2)

    # Split commission between two owners
    owner1_id = "944654043878400120"
    owner2_id = "617160222573592589"
    commission_split = round(commission_total / 2, 2)

    update_wallet(worker_id, "wallet_dollars", float(worker_payment), "$")
    update_wallet(owner1_id, "commission_dollars", float(commission_split), "$")
    update_wallet(owner2_id, "commission_dollars", float(commission_split), "$")
    helper_id = str(order.get("posted_by"))
    if helper_id:
        update_wallet(helper_id, "wallet_dollars", float(helper_payment), "$")
    else:
        print(f"[WARNING] Order {order_id} has no 'posted_by' — helper payment skipped.")


    # Mark order completed
    orders_collection.update_one({"_id": order_id}, {"$set": {"status": "completed"}})

    # Guild member check and roles
    guild = interaction.guild
    customer = guild.get_member(int(customer_id))
    if customer:
        spent_value = order["value"]
        await check_and_assign_roles(customer, 0, spent_value, interaction.client)
    else:
        print(f"[ERROR] Customer {customer_id} not found in the Discord server.")

    # Send order completion embed
    original_channel = bot.get_channel(order["original_channel_id"])
    if original_channel:
        embed = Embed(title="✅ Order Completed", color=discord.Color.from_rgb(139, 0, 0))
        embed.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        embed.add_field(name="📕 Description", value=order.get("description", "No description provided."), inline=False)
        embed.add_field(name="👷 Worker", value=f"<@{order['worker']}>", inline=True)
        embed.add_field(name="📌 Customer", value=f"<@{order['customer']}>", inline=True)
        embed.add_field(name="💰 Value", value=f"**{order['value']}$**", inline=True)
        embed.add_field(name="👷‍♂️ Worker Payment", value=f"**{worker_payment}$**", inline=True)
        embed.add_field(name="🏦 Server Commission", value=f"**{commission_total}$ (split 50/50)**", inline=True)
        embed.add_field(name="📬 Helper Reward", value=f"**{helper_payment}$**", inline=True)
        embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")
        embed.set_footer(text=f"📜 Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        await original_channel.send(embed=embed)

        # Security reminder
        security = Embed(
            title="🔒 Security Reminder",
            description=(f"**<@{customer_id}>**\n\n"
                         "__Please do the following immediately:__\n"
                         "• **Change your account password**\n"
                         "• **End All Sessions**\n"
                         "• **Change your bank PIN** (Optional)\n"),
            color=discord.Color.gold()
        )
        security.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        security.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        security.set_footer(text="Cynx System • Please confirm once done", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        security.add_field(name="⚠️ Action Required", value="**This is for your safety. Please confirm here once changed.**", inline=False)
        await original_channel.send(content=f"<@{customer_id}>", embed=security)

    # DM worker confirmation
    worker = bot.get_user(order["worker"])
    if worker:
        dm_embed = Embed(title="✅ Order Completed", color=discord.Color.from_rgb(139, 0, 0))
        dm_embed.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        dm_embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        dm_embed.add_field(name="📕 Description", value=order.get("description", "No description provided."), inline=False)
        dm_embed.add_field(name="💰 Value", value=f"**{order['value']}$**", inline=True)
        dm_embed.add_field(name="👷‍♂️ Your Payment", value=f"**{worker_payment}$**", inline=True)
        dm_embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif")
        dm_embed.set_footer(text=f"📜 Order ID: {order_id}", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        try:
            await worker.send(embed=dm_embed)
        except discord.Forbidden:
            print(f"[WARNING] Could not DM worker {worker.id}. DMs may be closed.")
    # Notify the helper in a specific channel
    helper_id = str(order.get("posted_by", interaction.user.id))
    helper_channel = bot.get_channel(1395073687199416411)

    if helper_channel:
        helper_embed = Embed(title="🎯 Helper Commission Summary", color=discord.Color.gold())
        helper_embed.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        helper_embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        helper_embed.add_field(name="📜 Order ID", value=f"`{order_id}`", inline=True)
        helper_embed.add_field(name="💰 Order Value", value=f"**```{order['value']}$```**", inline=True)
        helper_embed.add_field(name="🎁 Your Share", value=f"**```{helper_payment}$```**", inline=True)
        helper_embed.set_footer(text=f"Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif")
        try:
            await helper_channel.send(f"<@{helper_id}>", embed=helper_embed)
        except Exception as e:
            print(f"[ERROR] Failed to send helper embed: {e}")
            
    await interaction.response.send_message("✅ Order marked as completed successfully!", ephemeral=True)
    await log_command(interaction, "Order Completed", (
        f"Order ID: {order_id}\nMarked by: {interaction.user.mention} (`{interaction.user.id}`)\n"
        f"Worker: <@{order['worker']}> (`{order['worker']}`)\n"
        f"Customer: <@{order['customer']}> (`{order['customer']}`)\n"
        f"Value: {total_value}$\nWorker Payment: {worker_payment}$\n"
        f"Server Commission: {commission_value}$\nHelper Reward: {helper_payment}$"
     ))
@bot.tree.command(name="commission", description="Add or remove funds from a user's commission wallet ($ only).")
@app_commands.describe(
    user="The user to modify commission for.",
    action="Choose whether to add or remove funds.",
    amount="Amount in USD to add or remove."
)
@app_commands.choices(
    action=[
        app_commands.Choice(name="Add", value="add"),
        app_commands.Choice(name="Remove", value="remove")
    ]
)
async def commission(interaction: discord.Interaction, user: discord.User, action: app_commands.Choice[str], amount: float):
    # --- Role restriction ---
    allowed_roles = {1208792946430836736, 1208792946401615900}
    user_roles = {role.id for role in interaction.user.roles}

    if not (allowed_roles & user_roles):
        await interaction.response.send_message("🚫 You don't have permission to use this command.", ephemeral=True)
        return

    user_id = str(user.id)
    wallet = db.wallets.find_one({"user_id": user_id})

    if not wallet:
        wallet = {"user_id": user_id, "wallet_dollars": 0, "commission_dollars": 0}
        db.wallets.insert_one(wallet)

    old_balance = wallet.get("commission_dollars", 0)

    # --- Perform the update ---
    if action.value == "add":
        new_balance = old_balance + amount
        update_text = f"➕ Added **${amount:,.2f}** to {user.mention}'s commission wallet."
        color = 0x00ff99
    else:
        new_balance = old_balance - amount
        update_text = f"➖ Removed **${amount:,.2f}** from {user.mention}'s commission wallet."
        color = 0xff5555

    # Update MongoDB
    db.wallets.update_one(
        {"user_id": user_id},
        {"$set": {"commission_dollars": new_balance}}
    )

    # --- Confirmation Embed ---
    embed = discord.Embed(
        title="💼 Commission Wallet Updated",
        description=update_text,
        color=color
    )
    embed.add_field(name="Previous Balance", value=f"${old_balance:,.2f}", inline=True)
    embed.add_field(name="New Balance", value=f"${new_balance:,.2f}", inline=True)
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.set_footer(
        text=f"Action by {interaction.user} • {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )

    await interaction.response.send_message(embed=embed)

    # --- Log Embed ---
    log_channel_id = 1345311951747813450
    log_channel = interaction.guild.get_channel(log_channel_id)

    if log_channel:
        log_embed = discord.Embed(
            title="📜 Commission Wallet Log",
            color=0xffcc00,
            timestamp=datetime.now()
        )
        log_embed.add_field(name="Action", value=action.value.capitalize(), inline=True)
        log_embed.add_field(name="Amount", value=f"${amount:,.2f}", inline=True)
        log_embed.add_field(name="Old Balance", value=f"${old_balance:,.2f}", inline=True)
        log_embed.add_field(name="New Balance", value=f"${new_balance:,.2f}", inline=True)
        log_embed.add_field(name="Target User", value=f"{user.mention}", inline=True)
        log_embed.add_field(name="Executed By", value=f"{interaction.user.mention}", inline=False)
        log_embed.set_footer(text=f"User ID: {user.id}")

        await log_channel.send(embed=log_embed)



@bot.tree.command(name="summary", description="Show users with wallet balances and ongoing orders.")
async def summary(interaction: discord.Interaction):
    if not has_permission(interaction.user):
        await interaction.response.send_message("❌ You don't have permission to use this command.", ephemeral=True)
        return

    # === Wallet Overview ===
    wallets = list(wallets_collection.find({
        "$or": [
            {"wallet": {"$gt": 0}},
            {"deposit": {"$gt": 0}}
        ]
    }))

    wallet_summary = ""
    for w in wallets:
        user_id = w.get("user_id", "Unknown")
        wallet_amount = w.get("wallet", 0)
        deposit_amount = w.get("deposit", 0)
        spent_amount = w.get("spent", 0)
        wallet_summary += f"<@{user_id}> → 💵 **{wallet_amount}M** | 🏦 Deposit: **{deposit_amount}M** | 🎃 Spent: **{spent_amount}M**\n"

    if not wallet_summary:
        wallet_summary = "_No users have money in their wallet or deposit._"

    # === Orders Overview ===
    in_progress_orders = list(orders_collection.find({
        "$or": [
            {"status": {"$in": ["in_progress", "claimed"]}},
            {"completed": {"$ne": True}}
        ]
    }))

    order_summary = ""
    for o in in_progress_orders:
        order_id = o.get("_id", "N/A")
        worker = o.get("worker")
        customer = o.get("customer")
        order_summary += f"🆔 **Order {order_id}** → 👷 {f'<@{worker}>' if worker else 'Unassigned'} | 👤 {f'<@{customer}>' if customer else 'Unknown'}\n"

    if not order_summary:
        order_summary = "_No ongoing orders found._"

    # === Create Embed ===
    embed = discord.Embed(
        title="📊 System Summary",
        description="Overview of wallet balances and active orders",
        color=discord.Color.from_rgb(139, 0, 0)
    )
    embed.add_field(name="💰 Users With Wallets", value=wallet_summary[:1024], inline=False)
    embed.add_field(name="📦 Orders In Progress", value=order_summary[:1024], inline=False)
    embed.set_footer(text=f"Requested by {interaction.user.display_name}", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)

    await interaction.response.send_message(embed=embed)

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
    embed.set_author(name="Cynx System", icon_url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&=")
    embed.add_field(name="👷 Worker", value=f"<@{worker_id}>" if isinstance(worker_id, int) else worker_id, inline=False)
    embed.add_field(name="📌 Customer", value=f"<@{customer_id}>" if isinstance(customer_id, int) else customer_id, inline=False)
    embed.add_field(name="🎟️ Holder", value=f"<@{holder_id}>" if isinstance(holder_id, int) else holder_id, inline=False)
    embed.add_field(name="📕 Description", value=description, inline=False)
    embed.add_field(name="💵 Deposit", value=f"**```{deposit}M```**", inline=True)
    embed.add_field(name="💰 Order Value", value=f"**```{value}M```**", inline=True)
    embed.add_field(name="🆔 Order ID", value=order_id, inline=False)
    embed.set_image(url="https://media.discordapp.net/attachments/985890908027367474/1258798457318019153/Cynx_banner.gif?ex=67bf2b6b&is=67bdd9eb&hm=ac2c065a9b39c3526624f939f4af2b1457abb29bfb8d56a6f2ab3eafdb2bb467&=")
    embed.set_thumbnail(url="https://media.discordapp.net/attachments/1208792947232079955/1376855814735921212/discord_with_services_avatar.gif?ex=6836d866&is=683586e6&hm=c818d597519f4b2e55c77aeae4affbf0397e12591743e1069582f605c125f80c&=")
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
