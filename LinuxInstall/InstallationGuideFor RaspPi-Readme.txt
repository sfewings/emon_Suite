1. 	Install node-red, nginx, 
2. 	Build paho_mqtt_c and paho.mqtt.cpp
	
3.	Build /share/Emon_LogToJson using /bin/sh GCC_Build.txt.sh from inside path /share/Emon_LogToJson/
4.	Build /share/Emon_SerialToMQTT using /bin/sh GCC_Build.txt.sh in folder /share/Emon_SerialToMQTT/
5   To run manually, use the command lines in /share/Emon_LogToJson/Emon_LogToJson.sh and /share/Emon_SerialToMQTT/Emon_SerialToMQTT.sh

1.	Enable Emon_LogToJson and Emon_SerialToMQTT
	/etc/systemd/system/Emon_LogToJson.service
	/etc/systemd/system/Emon_SerialToMQTT.service
	#To install 	1. sudo copy to /etc/systemd/system
	#		2. sudo systemctl enable Emon_LogToJson
	//note sympolic link to files in /etc/systemd/system/multi-user.target.wants

2. 	Install nginx
	Copy contents of /etc/nginx/sites-available/default
	This enables shannstainable.fewings.org http and https traffic to node-red on port :1880\ui

3. 	Enable projects in node-red
	in /home/pi/.node-red/settings.js     
	// Customising the editor
    editorTheme: {
        projects: {
            // To enable the Projects feature, set this value to true
            enabled: true
			
4.	Create SSL certificate for shannstainable.fewings.org using letsencrypt
	/etc/letsencrypt/live/shannstainable.fewings.org/cert.pem
	Set up renewal every 40 days by placing /etc/letsencrypt/renewal/shannstainable.fewings.org.conf

5. Auto DNS shannstainable.fewings.org
	Ass this line to the crontab file. Run crontab -e
	#run the dyndns every 30 minutes
	30 * * * * /usr/bin/curl --insecure -d "u=steve&p=5yufdsHyf6" https://mike.fewings.org/dyndns.php >> /share/log/curl_cron.log 2>&1
	Note that it logs each execution in the file /share/log/curl_cron.log
	
	