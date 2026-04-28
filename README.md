# Coffee_Shop System 

Ready to start your Coffee Shop?

You need the database server to be up and running. To do this, you need to have PostgreSQL locally installed on your computer. You need to know the path to your database cluster.
Then, launch a terminal window/command prompt and start your database server. Using the command "pg_ctl -D /usr/local/pgsql/data/ start"

pg_ctl is the application that runs the server. -D flag followed by the path to your database cluster, in my case the path is "/usr/local/pgsql/data/" Followed by start to tell the "pg_ctl" app to start running the server.

Open another separate terminal/command prompt window and establish a connection with the database. using the command "psql -h localhost -p 5433 -U mit -d coffee_shop"
Where; psql is another application, feeding in parameters, -h flag with the hosting address. In my case i host it on "localhost" -p flag with the port number that the database server is listening on (the database server you want to connect to). In my case, the host number is 5433 -U flag with the user name you want to use, to establish a connection to the database. in my case, i am connecting as the user "mit" -d flag with the database name that you want to connect to. In my case, I am connecting to the database named "coffee_shop"

Then you can make a copy of these files(flaskdemo5.py and the templates folder) and put them in a specific folder name of your choice.
Make sure to edit the database content at the top of the flaskdemo5.py file to match the command "psql -h localhost -p 5433 -U mit -d coffee_shop" based on your hosting address, port number, databaseName, userName to have a well established connection.
Save the changes
Run the command "python3 flaskdemo5.py" (or "python flaskdemo5.py") from the folder you put these files in.
As you edit content on the web app, you can use the window connected to the database to run queries and see the changes.
