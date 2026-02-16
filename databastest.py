import mysql.connector

conn = mysql.connector.connect(
    host="172.20.18.2",
    user="cinema_user",
    password="Cinema1919!",
    database="cinema_db"
)

print("Verbinding geslaagd!")

conn.close()
