/* Settings page (/admin/settings). Strings come from the page's inline I18N object,
   ADMIN_ACCOUNT_CREATED from the server, TitleDB languages from #settingsLanguages. */

settings_map = {
    'library/path': 'libraryPathInput'
};


// allUsers = [];

function getInputVal(inputId) {
    return $("#" + inputId).val();
};

function setInputVal(inputId, value) {
    return $("#" + inputId).val(value);
};

function getCheckboxStatus(checkboxId) {
    return $('#' + checkboxId).is(":checked")
}

// Scans one library, or every configured one when path is null.
const SCAN_MUTATION = `
    mutation Scan($path: String) {
        scanLibrary(path: $path) { id status }
    }`;

async function scanLibrary(path = null) {
    $('.scanBtn').prop('disabled', true);
    try {
        const r = await fetch('/api/graphql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({query: SCAN_MUTATION, variables: {path: path}}),
        });
        if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
        const body = await r.json();
        if (body.errors && body.errors.length) {
            throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
        }
        console.log('Scan enqueued:', body.data.scanLibrary);
        showPathsError(null);
    } catch (e) {
        console.error(e);
        showPathsError('Could not start scan: ' + e.message);
    } finally {
        $('.scanBtn').prop('disabled', false);
    }
}

// Shows API `errors` (or a plain message) above the paths table; falsy clears it.
function showPathsError(errors) {
    const text = Array.isArray(errors) ? errors.map(e => e.error || e).join(' ') : errors;
    $('#pathsAlert').text(text || '').toggleClass('d-none', !text);
}

function fillLibraryTable() {
    $('#pathsTable tbody').empty();

    $.getJSON("/api/settings/library/paths", function (result) {

        if (!result['success']) {
            if (result['status_code'] == '302') {
                window.location.href = result['location']
                return
            }
        }
        paths = result.paths;
        if (paths === null || !paths.length) {
            $('#pathsTable tbody').append(
                '<tr><td>-</td><td>-</td><td>');
        } else {
            paths.forEach(path => {
                // The path is set with .text()/.attr(): concatenating it into markup, or into an
                // inline handler, makes the browser eat backslashes in Windows paths (issue #297).
                const scanBtn = $('<button type="button" class="btn btn-outline-info btn-sm scanBtn"><i class="bi bi-arrow-clockwise"></i></button>').attr('data-bs-path', path);
                const deleteBtn = $('<button type="button" class="btn btn-outline-danger btn-sm" data-bs-toggle="modal" data-bs-target="#deletePathModal"><i class="bi bi-x-circle"></i></button>').attr('data-bs-path', path);
                $('#pathsTable tbody').append(
                    $('<tr>').append($('<td>').text(path), $('<td>').append(scanBtn, ' ', deleteBtn)));
            })
        }
        const watcher = result.watcher || { enabled: true, polling_interval: 60 };
        $('#watcherEnabledCheck').prop('checked', watcher.enabled);
        $('#watcherIntervalInput').val(watcher.polling_interval);
    });

}

function submitWatcherSettings() {
    $('#submitWatcherSettingsBtn').prop('disabled', true);
    data = {
        enabled: getCheckboxStatus("watcherEnabledCheck"),
        polling_interval: parseInt($('#watcherIntervalInput').val(), 10)
    }
    $.ajax({
        url: "/api/settings/library/watcher",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (!result['success']) {
                if (result['errors']) {
                    result['errors'].forEach(error => {
                        $('#watcherIntervalFeedback').text(error['error']);
                        $('#watcherIntervalFeedback').addClass('invalid-feedback d-block');
                        $("#watcherIntervalInput").removeClass('is-valid').addClass('is-invalid');
                    });
                }
            } else {
                $('#watcherIntervalFeedback').text('').removeClass('invalid-feedback d-block');
                $("#watcherIntervalInput").removeClass('is-invalid').addClass('is-valid');
            }
            $('#submitWatcherSettingsBtn').prop('disabled', false);
        }
    });
}

function fillUserTable() {
    $('#userTable tbody').empty();
    $.getJSON("/api/users", function (result) {
        if (!result['success']) {
            if (result['status_code'] == '302') {
                window.location.href = result['location']
                return
            }
        }
        allUsers = result;
        allUsernames = [];
        if (!result.length) {
            $('#userTable tbody').append(
                '<tr><td>-</td><td>-</td><td>-</td></tr>');
        }
        result.forEach(user => {
            allUsernames.push(user['user']);
            // Built as nodes, not concatenated markup: a username is free text.
            const perms = $('<td>');
            [['shop_access', I18N.shop], ['backup_access', I18N.backup], ['admin_access', I18N.admin]]
                .forEach(([key, label]) => {
                    perms.append($('<div class="form-check form-check-inline">').append(
                        $('<input class="form-check-input" type="checkbox" onclick="return false">')
                            .prop('checked', Boolean(user[key])),
                        $('<label class="form-check-label">').text(label)));
                });
            const actions = $('<td>').append(
                $('<button type="button" class="btn btn-outline-info btn-sm me-1" data-bs-toggle="modal" data-bs-target="#editUserModal"><i class="bi bi-pencil-square"></i></button>')
                    .attr({'data-bs-id': user['id'], 'title': I18N.editTooltip}),
                $('<button type="button" class="btn btn-outline-danger btn-sm" data-bs-toggle="modal" data-bs-target="#deleteUserModal"><i class="bi bi-x-circle"></i></button>')
                    .attr({'data-bs-id': user['id'], 'data-bs-user': user['user']}));
            $('#userTable tbody').append($('<tr>').append($('<td>').text(user['user']), perms, actions));
        });
    })

}

function updateKeysElements(titlesSettings) {
    // Verification cannot run without keys: nstools needs them to open a container.
    const validKeys = Boolean(titlesSettings['valid_keys']);
    $('#verifyFilesCheck, #verificationDepthSignature, #verificationDepthHash').prop('disabled', !validKeys);
    $('#verificationKeysAlert').toggleClass('d-none', validKeys);

    // Keys alert
    if (titlesSettings['valid_keys']) {
        $('#consoleKeysFeedback').text("Keys are valid!");
        $('#consoleKeysFeedback').removeClass('invalid-feedback');
        $('#consoleKeysFeedback').addClass('valid-feedback d-block');
        $('#missingKeysAlert').removeClass('d-block');
        $('#missingKeysAlert').addClass('d-none');
    } else {
        $('#consoleKeysFeedback').removeClass('valid-feedback');
        $('#consoleKeysFeedback').addClass('invalid-feedback d-block');
        $('#missingKeysAlert').removeClass('d-none');
        $("#missingKeysAlert").addClass('d-block');
        if (titlesSettings['valid_keys'] === null) {
            $('#consoleKeysFeedback').text("Missing keys file! Use the button above to upload a new file.");
        } else {
            $('#consoleKeysFeedback').text("Invalid keys file! At least one master key is incorrect. Use the button above to upload a new file.");
        }
    }

    // Missing and invalid master key revisions
    if (titlesSettings['valid_keys'] === null) {
        $('#keysAlert').css("border-color", "var(--bs-danger-border-subtle)");
        $("#keysMissingLabel").text("Missing console keys file.");
    } else if ((titlesSettings['missing_keys'] && titlesSettings['missing_keys'].length > 0) || (titlesSettings['corrupt_keys'] && titlesSettings['corrupt_keys'].length > 0)) {
        $('#keysAlert').css("border-color", "var(--bs-warning-border-subtle)");
        $("#keysMissingLabel").text("Missing/invalid master key revisions:");
        $("#keysMissingLabel").next('ul').remove(); // Clear existing ul if any
        var ul = $('<ul class="mb-0">');
        if (titlesSettings['corrupt_keys'] && titlesSettings['corrupt_keys'].length > 0) {
            $.each(titlesSettings['corrupt_keys'], function(index, key) {
                ul.append($('<li>').html('<code>' + key + '</code> is invalid'));
            });
        }
        if (titlesSettings['missing_keys'] && titlesSettings['missing_keys'].length > 0) {
            $.each(titlesSettings['missing_keys'], function(index, key) {
                ul.append($('<li>').html('<code>' + key + '</code> is missing'));
            });
        }
        $("#keysMissingLabel").after(ul);
    } else {
        $('#keysAlert').css("border-color", "var(--bs-form-valid-border-color)");
        $("#keysMissingLabel").text("All master key revisions are present and valid.");
    }
}

// Row buttons carry their path in data-bs-path, read back as a string rather than
// re-parsed as markup or JS.
$('#pathsTable').on('click', '.scanBtn', function () {
    scanLibrary($(this).attr('data-bs-path'))
})

const deletePathModal = $('#deletePathModal')
if (deletePathModal) {
    deletePathModal.on('show.bs.modal', event => {
        const path = event.relatedTarget.getAttribute('data-bs-path')
        deletePathModal.data('path', path)
        deletePathModal.find('.modal-body').text("Delete path " + path + " ?")
    })
    deletePathModal.find('.btn-danger').on('click', () => deleteLibraryPath(deletePathModal.data('path')))
}

const deleteUserModal = $('#deleteUserModal')
if (deleteUserModal) {
    deleteUserModal.on('show.bs.modal', event => {
        // Button that triggered the modal
        const button = event.relatedTarget
        // Extract info from data-bs-* attributes
        const user = button.getAttribute('data-bs-user')
        const id = button.getAttribute('data-bs-id')
        // If necessary, you could initiate an Ajax request here
        // and then do the updating in a callback.

        // Update the modal's content.
        // const modalTitle = deleteUserModal.querySelector('.modal-title')
        const modalBody = deleteUserModal.find('.modal-body')
        const deleteBtn = deleteUserModal.find('.btn-danger')


        deleteBtn.off('click').on('click', () => deleteUser(Number(id)));

        modalBody.text(I18N.deleteUserConfirm.replace('__USER__', user))
    })
}

function showUsersError(message) {
    $('#usersAlert').text(message || '').toggleClass('d-none', !message);
}

function deleteUser(userId) {
    data = {
        user_id: userId
    }
    $.ajax({
        url: "/api/user",
        type: 'DELETE',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            showUsersError(result['success'] ? null : result['error']);
            if (result['success']) {
                fillUserTable();
            }
        }
    });
}

const editUserModal = $('#editUserModal');
function syncEditUserAdminCheckbox() {
    const isAdmin = $('#checkboxEditUserAdminAccess').prop('checked');
    if (isAdmin) {
        $('#checkboxEditUserShopAccess, #checkboxEditUserBackupAccess').prop('checked', true);
    }
    $('#checkboxEditUserShopAccess, #checkboxEditUserBackupAccess').prop('disabled', isAdmin);
}
$('#checkboxEditUserAdminAccess').on('change', syncEditUserAdminCheckbox);
editUserModal.on('show.bs.modal', event => {
    const id = Number(event.relatedTarget.getAttribute('data-bs-id'));
    const user = (allUsers || []).find(u => u['id'] === id);
    if (!user) return;
    editUserModal.data('userId', id);
    $('#inputEditUser').val(user['user']);
    $('#inputEditUserPassword').val('').removeClass('is-invalid');
    $('#checkboxEditUserShopAccess').prop('checked', Boolean(user['shop_access']));
    $('#checkboxEditUserBackupAccess').prop('checked', Boolean(user['backup_access']));
    $('#checkboxEditUserAdminAccess').prop('checked', Boolean(user['admin_access']));
    syncEditUserAdminCheckbox();
    $('#editUserAlert').addClass('d-none').text('');
});
$('#editUserSaveBtn').on('click', () => {
    const password = $('#inputEditUserPassword').val();
    if (password) {
        const validation = validatePassword(password);
        if (!validation.isValid) {
            $('#editUserAlert').text(validation.message).removeClass('d-none');
            return;
        }
    }
    $.ajax({
        url: "/api/user",
        type: 'PATCH',
        data: JSON.stringify({
            user_id: editUserModal.data('userId'),
            password: password,
            shop_access: $('#checkboxEditUserShopAccess').prop('checked'),
            backup_access: $('#checkboxEditUserBackupAccess').prop('checked'),
            admin_access: $('#checkboxEditUserAdminAccess').prop('checked'),
        }),
        contentType: "application/json",
        success: function (result) {
            if (result['success']) {
                bootstrap.Modal.getInstance(editUserModal[0]).hide();
                fillUserTable();
            } else {
                $('#editUserAlert').text(result['error']).removeClass('d-none');
            }
        },
        error: function (xhr) {
            const message = (xhr.responseJSON && xhr.responseJSON.error) || ('HTTP ' + xhr.status);
            $('#editUserAlert').text(message).removeClass('d-none');
        }
    });
});

function deleteLibraryPath(path) {
    data = {
        path: path
    }
    $.ajax({
        url: "/api/settings/library/paths",
        type: 'DELETE',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            showPathsError(result['success'] ? null : result['errors']);
            if (result['success']) {
                fillLibraryTable();
            }
        },
        error: function (xhr) {
            showPathsError('Could not delete path: HTTP ' + xhr.status + '.');
        }
    });
}

$('#checkboxNewUserAdminAccess').change(function () {
    if (this.checked != false) {
        $('#checkboxNewUserShopAccess').prop('checked', true).attr("disabled", true);
        $('#checkboxNewUserBackupAccess').prop('checked', true).attr("disabled", true);

    } else {
        $('#checkboxNewUserShopAccess').attr("disabled", false);
        $('#checkboxNewUserBackupAccess').attr("disabled", false);

    }
});

function validatePassword(password) {
    if (!password) {
        return {
            isValid: false,
            message: "Password cannot be empty"
        };
    }
    
    // Check for control characters (null, line breaks, etc.)
    const controlChars = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/;
    if (controlChars.test(password)) {
        return {
            isValid: false,
            message: "Password contains invalid control characters"
        };
    }
    
    // Also check for tab, newline, and carriage return explicitly
    if (password.includes('\t') || password.includes('\n') || password.includes('\r')) {
        return {
            isValid: false,
            message: "Password contains invalid control characters"
        };
    }
    
    // Check for Tinfoil forbidden characters
    const tinfoilForbidden = /[@&/?#=]/;
    if (tinfoilForbidden.test(password)) {
        return {
            isValid: false,
            message: "Password contains invalid characters. Please avoid: @ & / ? # ="
        };
    }
    
    // Check for UTF-8 encoding validity
    try {
        // Try to encode as UTF-8
        new TextEncoder().encode(password);
    } catch (e) {
        return {
            isValid: false,
            message: "Password contains invalid UTF-8 characters"
        };
    }
    
    return { isValid: true, message: "" };
}

function validateUsername(username) {
    if (!username) {
        return {
            isValid: false,
            message: "Username cannot be empty"
        };
    }
    
    // Check for colons (not allowed in Basic Auth usernames)
    if (username.includes(':')) {
        return {
            isValid: false,
            message: "Username cannot contain colons (:)"
        };
    }
    
    // Check for control characters (null, line breaks, etc.)
    const controlChars = /[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/;
    if (controlChars.test(username)) {
        return {
            isValid: false,
            message: "Username contains invalid control characters"
        };
    }
    
    // Also check for tab, newline, and carriage return explicitly
    if (username.includes('\t') || username.includes('\n') || username.includes('\r')) {
        return {
            isValid: false,
            message: "Username contains invalid control characters"
        };
    }
    
    // Check for UTF-8 encoding validity
    try {
        // Try to encode as UTF-8
        new TextEncoder().encode(username);
    } catch (e) {
        return {
            isValid: false,
            message: "Username contains invalid UTF-8 characters"
        };
    }
    
    return { isValid: true, message: "" };
}

function showPasswordError(message) {
    $('#inputNewUserPassword').addClass('is-invalid');
    let errorDiv = $('#inputNewUserPassword').siblings('.invalid-feedback');
    if (errorDiv.length === 0) {
        errorDiv = $('<div class="invalid-feedback"></div>');
        $('#inputNewUserPassword').after(errorDiv);
    }
    errorDiv.text(message);
}

function clearPasswordError() {
    $('#inputNewUserPassword').removeClass('is-invalid');
    $('#inputNewUserPassword').siblings('.invalid-feedback').remove();
}

function showUsernameError(message) {
    $('#inputNewUser').addClass('is-invalid');
    let errorDiv = $('#inputNewUser').siblings('.invalid-feedback');
    if (errorDiv.length === 0) {
        errorDiv = $('<div class="invalid-feedback"></div>');
        $('#inputNewUser').after(errorDiv);
    }
    errorDiv.text(message);
}

function clearUsernameError() {
    $('#inputNewUser').removeClass('is-invalid');
    $('#inputNewUser').siblings('.invalid-feedback').remove();
}

function submitNewUser() {
    formOk = true;
    user = getInputVal("inputNewUser")
    password = getInputVal("inputNewUserPassword")
    shop_access = getCheckboxStatus("checkboxNewUserShopAccess")
    backup_access = getCheckboxStatus("checkboxNewUserBackupAccess")
    admin_access = getCheckboxStatus("checkboxNewUserAdminAccess")

    // Validate username
    const usernameValidation = validateUsername(user);
    if (!usernameValidation.isValid) {
        showUsernameError(usernameValidation.message);
        formOk = false;
    } else if (allUsernames.includes(user)) {
        showUsernameError('User already exists');
        formOk = false;
    } else {
        clearUsernameError();
    }

    // Validate password
    const passwordValidation = validatePassword(password);
    if (!passwordValidation.isValid) {
        showPasswordError(passwordValidation.message);
        formOk = false;
    } else {
        clearPasswordError();
    }


    if (formOk) {
        data = {
            user: user,
            password: password,
            shop_access: shop_access,
            backup_access: backup_access,
            admin_access: admin_access,
        }

        $.ajax({
            url: "/api/user/signup",
            type: 'POST',
            data: JSON.stringify(data),
            contentType: "application/json",
            success: function (result) {
                if (result['success']) {
                    if (result['status_code'] == '302') {
                        window.location.href = result['location']
                        return
                    }
                    console.log('Signup Success!');
                    setInputVal("inputNewUser", "")
                    setInputVal("inputNewUserPassword", "")
                    fillUserTable();
                } else {
                    // Handle backend validation errors
                    if (result['error']) {
                        $('#inputNewUserPassword').addClass('is-invalid');
                        let errorDiv = $('#inputNewUserPassword').siblings('.invalid-feedback');
                        if (errorDiv.length === 0) {
                            errorDiv = $('<div class="invalid-feedback"></div>');
                            $('#inputNewUserPassword').after(errorDiv);
                        }
                        errorDiv.text(result['error']);
                    }
                }
            },
            error: function(xhr, status, error) {
                console.error('Error creating user:', error);
                $('#inputNewUserPassword').addClass('is-invalid');
                let errorDiv = $('#inputNewUserPassword').siblings('.invalid-feedback');
                if (errorDiv.length === 0) {
                    errorDiv = $('<div class="invalid-feedback"></div>');
                    $('#inputNewUserPassword').after(errorDiv);
                }
                errorDiv.text('Error creating user. Please try again.');
            }
        });
    }
}

function submitNewLibraryPath() {
    $('#submitNewLibraryPathBtn').prop('disabled', true);
    path = getInputVal("libraryPathInput").trim();
    data = {
        path: path
    }

    $.ajax({
        url: "/api/settings/library/paths",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (result['success']) {
                if (result['status_code'] == '302') {
                    window.location.href = result['location']
                    return
                }
                console.log('Sucessfully added path ' + path);
                setInputVal("libraryPathInput", "")
                showPathsError(null);
                fillLibraryTable();
            } else {
                showPathsError(result['errors']);
            }
            $('#submitNewLibraryPathBtn').prop('disabled', false);
        },
        error: function (xhr) {
            showPathsError('Could not add path: HTTP ' + xhr.status + '.');
            $('#submitNewLibraryPathBtn').prop('disabled', false);
        }
    });
}

function submitTitlesSettings() {
    $('#submitTitlesSettingsBtn').prop('disabled', true);
    data = {
        region: getInputVal("selectRegion"),
        language: getInputVal("selectLanguage"),
    }
    file = $('#consoleKeysInput').prop('files')[0];

    if (file != undefined) {
        formData = new FormData();
        formData.append("file", file);
        $.ajax({
            url: "/api/upload",
            type: 'POST',
            data: formData,
            cache: false,
            contentType: false,
            processData: false,
            success: function (result) {
                if (result['success']) {
                    updateKeysElements(result['data']);
                    $('#consoleKeysInput').val('');
                } else {
                    errors = result['errors'].join(';')
                    $('#consoleKeysFeedback').text("Failed to upload keys file: " + errors);
                    $('#consoleKeysFeedback').addClass('invalid-feedback d-block');
                }
            }
        });
    }

    $.ajax({
        url: "/api/settings/titles",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (!result['success']) {
                console.log('Not Success!');
                result['errors'].forEach(error => {
                    path = error['path'];
                    formId = settings_map[path];
                    form = $('#' + formId);
                    form.addClass('is-invalid');
                    formTextElement = form.attr('aria-describedby');
                    $("#" + formTextElement).addClass('invalid-feedback');
                    $("#" + formTextElement).text(error['error']);
                });
            }
            $('#consoleKeysInput').val('');
            $('#submitTitlesSettingsBtn').prop('disabled', false);
        }
    });
}

// Artwork kinds in the order they are shown, labelled for the usage table.
const MEDIA_KINDS = { icon: I18N.mediaKindIcon, banner: I18N.mediaKindBanner, screenshot: I18N.mediaKindScreenshot };

// Renditions in the order they are shown, one column each ahead of the total.
const MEDIA_SIZES = ['original', 'thumb', 'client', 'screen'];

function usageRow(label, bytes, bold) {
    const row = $(bold ? '<tr class="fw-semibold">' : '<tr>');
    const total = bytes.reduce((sum, used) => sum + used, 0);
    return row.append($('<td>').text(label), ...bytes.map(used => $('<td>').text(formatBytes(used))),
        $('<td>').text(formatBytes(total)));
}

function fillMediaUsage() {
    $.getJSON("/api/settings/local_media/usage", function (usage) {
        const rows = [];
        const totals = MEDIA_SIZES.map(() => 0);
        let files = 0;
        Object.entries(MEDIA_KINDS).forEach(([kind, label]) => {
            const bytes = MEDIA_SIZES.map((size, i) => {
                const used = ((usage[kind] || {})[size]) || { bytes: 0, files: 0 };
                files += used.files;
                totals[i] += used.bytes;
                return used.bytes;
            });
            rows.push(usageRow(label, bytes, false));
        });
        rows.push(usageRow(I18N.mediaColTotal, totals, true));
        $('#mediaUsageTable tbody').empty().append(rows);
        $('#mediaUsageCaption').text(I18N.mediaFilesStored.replace('{n}', files).replace(/\{s\}/g, files === 1 ? '' : 's'));
    });
}
$('#mediaUsage').on('show.bs.collapse', fillMediaUsage);

function submitLocalMediaSettings() {
    $('#submitLocalMediaSettingsBtn').prop('disabled', true);
    $.ajax({
        url: "/api/settings/local_media",
        type: 'POST',
        data: JSON.stringify({ enabled: getCheckboxStatus("localMediaEnabledCheck") }),
        contentType: "application/json",
        success: function (result) {
            if ($('#mediaUsage').hasClass('show')) {
                fillMediaUsage();
            }
            $('#submitLocalMediaSettingsBtn').prop('disabled', false);
        }
    });
}

function submitShopSettings() {
    $('#submitShopSettingsBtn').prop('disabled', true);
    data = {
        name: $('#shopNameInput').val(),
        host: $('#shopHostInput').val(),
        public: getCheckboxStatus("publicShopCheck"),
        motd: $('#shopMotdTextArea').val(),
        clients: {
            cyberfoil: {
                enabled: getCheckboxStatus("cyberfoilEnabledCheck"),
            },
            tinfoil: {
                enabled: getCheckboxStatus("tinfoilEnabledCheck"),
                encrypt: getCheckboxStatus("tinfoilEncryptShopCheck"),
            },
            sphaira: {
                enabled: getCheckboxStatus("sphairaEnabledCheck"),
            }
        }
    }

    $.ajax({
        url: "/api/settings/shop",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (!result['success']) {
                console.log('Not Success!');
                result['errors'].forEach(error => {
                    path = error['path'];
                    formId = settings_map[path];
                    form = $('#' + formId);
                    form.addClass('is-invalid');
                    formTextElement = form.attr('aria-describedby');
                    $("#" + formTextElement).addClass('invalid-feedback');
                    $("#" + formTextElement).text(error['error']);
                });
            }
            $('#submitShopSettingsBtn').prop('disabled', false);
        }
    });
}

function submitLibraryManagementSettings() {
    $('#submitLibraryManagementSettingsBtn').prop('disabled', true);
    data = {
        compression: {
            enabled: getCheckboxStatus("compressFilesCheck"),
            level: parseInt(getInputVal("compressionLevelInput")),
            long_distance: getCheckboxStatus("compressLongDistanceCheck"),
            mode: getInputVal("compressModeSelect"),
            block_size_exponent: parseInt(getInputVal("compressBlockSizeInput")),
            threads: parseInt(getInputVal("compressThreadsInput"))
        },
        verification: {
            enabled: getCheckboxStatus("verifyFilesCheck"),
            depth: $("input[name='verificationDepth']:checked").val() || "signature"
        },
        delete_older_updates: getCheckboxStatus("deleteOlderUpdatesCheck"),
        web_downloads: {
            enabled: getCheckboxStatus("webDownloadsEnabledCheck")
        },
        duplicates: {
            auto_resolve: getCheckboxStatus("autoResolveDuplicatesCheck"),
            prefer_multicontent: getCheckboxStatus("preferMulticontentCheck"),
            prefer_larger_on_tie: getCheckboxStatus("preferLargerOnTieCheck"),
            compression_preference: getInputVal("compressionPreferenceSelect")
        },
        organizer: {
            enabled: getCheckboxStatus("organizerEnabledCheck"),
            remove_empty_folders: getCheckboxStatus("removeEmptyFoldersCheck"),
            windows_compatible: getCheckboxStatus("windowsCompatibleCheck"),
            clean_names: getCheckboxStatus("cleanNamesCheck"),
            show_background_image: getCheckboxStatus("showBackgroundImageCheck"),
            name_region: getInputVal("organizerNameRegionSelect"),
            name_language: getInputVal("organizerNameRegionSelect") ? getInputVal("organizerNameLanguageSelect") : "",
            templates: {
                base: getInputVal("baseTemplateInput"),
                update: getInputVal("updateTemplateInput"),
                dlc: getInputVal("dlcTemplateInput"),
                multi: getInputVal("multiTemplateInput")
            }
        }
    }

    $.ajax({
        url: "/api/settings/library/management",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (!result['success']) {
                console.log('Not Success!');
            }
            $('#submitLibraryManagementSettingsBtn').prop('disabled', false);
        }
    });
}

function fillMaintenanceSettings(m) {
    if (!m) return;
    $('#maintEnabledCheck').prop('checked', Boolean(m.enabled));
    $('#maintTimeInput').val(m.time);
    $('#maintBackupCheck').prop('checked', Boolean(m.backup));
    $('#maintBackupKeepInput').val(m.backup_keep);
    $('#maintScanCheck').prop('checked', Boolean(m.scan));
    $('#maintRemoveOutdatedCheck').prop('checked', Boolean(m.remove_outdated_updates));
    $('#maintVerifyAllSelect').val(m.verify_all);
    loadBackups();
}

function showMaintNextRun(nextRun) {
    $('#maintNextRun').text(nextRun
        ? I18N.maintNextRun.replace('__WHEN__', new Date(nextRun).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'}))
        : I18N.maintNotScheduled);
}

function renderBackups(list) {
    const tbody = $('#backupsTable tbody').empty();
    if (!list.length) {
        tbody.append($('<tr>').append($('<td colspan="3" class="text-secondary">').text(I18N.maintNoBackups)));
        return;
    }
    list.forEach(b => {
        const actions = $('<td>').append(
            $('<a class="btn btn-outline-info btn-sm me-1"><i class="bi bi-download"></i></a>')
                .attr({href: '/api/backups/' + encodeURIComponent(b.name), title: b.name}),
            $('<button type="button" class="btn btn-outline-danger btn-sm"><i class="bi bi-x-circle"></i></button>')
                .on('click', () => deleteBackup(b.name)));
        tbody.append($('<tr>').append(
            $('<td>').text(new Date(b.created).toLocaleString([], {dateStyle: 'medium', timeStyle: 'short'})),
            $('<td>').text(formatBytes(b.size)),
            actions));
    });
}

function loadBackups() {
    $.getJSON('/api/backups', result => {
        renderBackups(result.backups || []);
        showMaintNextRun(result.next_run);
    });
}

function deleteBackup(name) {
    if (!confirm(I18N.maintDeleteConfirm.replace('__NAME__', name))) return;
    $.ajax({url: '/api/backups/' + encodeURIComponent(name), type: 'DELETE',
            success: result => renderBackups(result.backups || [])});
}

// Saved on change: the page itself switches to the new style unless this browser
// picked its own in the theme menu (theme.js keeps that override).
$('input[name="defaultStyle"]').on('change', function () {
    const style = this.value;
    $.ajax({
        url: '/api/settings/appearance', type: 'POST', contentType: 'application/json',
        data: JSON.stringify({default_style: style}),
        success: result => {
            $('#appearanceFeedback').removeClass('text-success text-danger')
                .addClass(result.success ? 'text-success' : 'text-danger')
                .text(result.success ? I18N.maintSaved : (result.errors || []).map(e => e.error).join(', '));
            if (result.success && window.setServerStyle) window.setServerStyle(style);
        },
        error: xhr => $('#appearanceFeedback').addClass('text-danger').text('HTTP ' + xhr.status),
    });
});

$('#submitMaintSettingsBtn').on('click', function () {
    const btn = $(this).prop('disabled', true);
    $.ajax({
        url: '/api/settings/maintenance', type: 'POST', contentType: 'application/json',
        data: JSON.stringify({
            enabled: $('#maintEnabledCheck').prop('checked'),
            time: $('#maintTimeInput').val(),
            backup: $('#maintBackupCheck').prop('checked'),
            backup_keep: parseInt($('#maintBackupKeepInput').val()),
            scan: $('#maintScanCheck').prop('checked'),
            remove_outdated_updates: $('#maintRemoveOutdatedCheck').prop('checked'),
            verify_all: $('#maintVerifyAllSelect').val(),
        }),
        success: result => {
            $('#maintFeedback').removeClass('text-success text-danger')
                .addClass(result.success ? 'text-success' : 'text-danger')
                .text(result.success ? I18N.maintSaved : (result.errors || []).map(e => e.error).join(', '));
            if (result.success) showMaintNextRun(result.next_run);
        },
        error: xhr => $('#maintFeedback').addClass('text-danger').text('HTTP ' + xhr.status),
        complete: () => btn.prop('disabled', false),
    });
});

$('#backupNowBtn').on('click', function () {
    const btn = $(this).prop('disabled', true);
    $('#backupFeedback').removeClass('text-danger').text('');
    $.ajax({
        url: '/api/backups', type: 'POST',
        success: result => renderBackups(result.backups || []),
        error: xhr => $('#backupFeedback').addClass('text-danger')
            .text((xhr.responseJSON && xhr.responseJSON.error) || ('HTTP ' + xhr.status)),
        complete: () => btn.prop('disabled', false),
    });
});

function fillNotificationSettings(n) {
    if (!n) return;
    $('#notifEnabledCheck').prop('checked', Boolean(n.enabled));
    $('#notifLanguageSelect').val(n.language || 'en');
    $('.notif-event').each(function () {
        $(this).prop('checked', Boolean((n.events || {})[$(this).data('event')]));
    });
    $('.notif-provider').each(function () {
        $(this).prop('checked', Boolean((n[$(this).data('provider')] || {}).enabled));
    });
    $('#notifDiscordWebhook').val(n.discord.webhook_url);
    $('#notifTelegramToken').val(n.telegram.bot_token);
    $('#notifTelegramChat').val(n.telegram.chat_id);
    $('#notifNtfyServer').val(n.ntfy.server);
    $('#notifNtfyTopic').val(n.ntfy.topic);
    $('#notifNtfyToken').val(n.ntfy.token);
    $('#notifWebhookUrl').val(n.webhook.url);
}

function collectNotificationSettings() {
    const events = {};
    $('.notif-event').each(function () { events[$(this).data('event')] = $(this).prop('checked'); });
    const enabled = provider => $('.notif-provider[data-provider="' + provider + '"]').prop('checked');
    return {
        enabled: $('#notifEnabledCheck').prop('checked'),
        language: $('#notifLanguageSelect').val(),
        events: events,
        discord: {enabled: enabled('discord'), webhook_url: $('#notifDiscordWebhook').val()},
        telegram: {enabled: enabled('telegram'), bot_token: $('#notifTelegramToken').val(),
                   chat_id: $('#notifTelegramChat').val()},
        ntfy: {enabled: enabled('ntfy'), server: $('#notifNtfyServer').val(),
               topic: $('#notifNtfyTopic').val(), token: $('#notifNtfyToken').val()},
        webhook: {enabled: enabled('webhook'), url: $('#notifWebhookUrl').val()},
    };
}

function showNotifFeedback(message, ok) {
    $('#notifFeedback').text(message).removeClass('text-success text-danger')
        .addClass(ok ? 'text-success' : 'text-danger');
}

$('#submitNotifSettingsBtn').on('click', function () {
    const btn = $(this).prop('disabled', true);
    $.ajax({
        url: '/api/settings/notifications', type: 'POST', contentType: 'application/json',
        data: JSON.stringify(collectNotificationSettings()),
        success: result => showNotifFeedback(result.success ? I18N.notifSaved
            : (result.errors || []).map(e => e.error).join(', '), result.success),
        error: xhr => showNotifFeedback('HTTP ' + xhr.status, false),
        complete: () => btn.prop('disabled', false),
    });
});

$('#testNotifBtn').on('click', function () {
    const btn = $(this).prop('disabled', true);
    $.ajax({
        url: '/api/settings/notifications/test', type: 'POST', contentType: 'application/json',
        data: JSON.stringify(collectNotificationSettings()),
        success: result => {
            if (result.error === 'no_provider') return showNotifFeedback(I18N.notifNoProvider, false);
            const results = result.results || {};
            const ok = Object.keys(results).filter(p => results[p] === null);
            const failed = Object.keys(results).filter(p => results[p] !== null)
                .map(p => p + ' (' + I18N.notifTestFailed + ': ' + results[p] + ')');
            const parts = [];
            if (ok.length) parts.push(I18N.notifTestOk.replace('__PROVIDERS__', ok.join(', ')));
            parts.push(...failed);
            showNotifFeedback(parts.join(' · '), failed.length === 0);
        },
        error: xhr => showNotifFeedback('HTTP ' + xhr.status, false),
        complete: () => btn.prop('disabled', false),
    });
});

function submitSchedulerSettings() {
    $('#submitSchedulerSettingsBtn').prop('disabled', true);
    data = {
        titledb_update_interval: getInputVal("titledbUpdateIntervalInput").trim()
    }

    $.ajax({
        url: "/api/settings/scheduler",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (!result['success']) {
                console.log('Not Success!');
                if (result['errors']) {
                    result['errors'].forEach(error => {
                        if (error['path'] === 'scheduler/titledb_update_interval') {
                            $('#titledbUpdateIntervalFeedback').text(error['error']);
                            $('#titledbUpdateIntervalFeedback').addClass('invalid-feedback d-block');
                            $("#titledbUpdateIntervalInput").removeClass('is-valid');
                            $("#titledbUpdateIntervalInput").addClass('is-invalid');
                        }
                        console.log('Path:', error['path']);
                        console.log('Error:', error['error']);
                    });
                }
            } else {
                console.log('Scheduler settings updated successfully!');
                $('#titledbUpdateIntervalFeedback').text('');
                $('#titledbUpdateIntervalFeedback').removeClass('invalid-feedback d-block');
                $("#titledbUpdateIntervalInput").removeClass('is-invalid');
                $("#titledbUpdateIntervalInput").addClass('is-valid');
            }
            $('#submitSchedulerSettingsBtn').prop('disabled', false);
        }
    });
}

function submitWorkerSettings() {
    $('#submitWorkerSettingsBtn').prop('disabled', true);
    data = {
        count: parseInt($('#workerCountInput').val()),
        group_limits: {
            io: parseInt($('#ioLimitInput').val()),
            net: parseInt($('#netLimitInput').val())
        }
    }

    $.ajax({
        url: "/api/settings/worker",
        type: 'POST',
        data: JSON.stringify(data),
        contentType: "application/json",
        success: function (result) {
            if (!result['success']) {
                if (result['errors']) {
                    result['errors'].forEach(error => {
                        if (error['path'] === 'worker/count') {
                            $('#workerCountFeedback').text(error['error']);
                            $('#workerCountFeedback').addClass('invalid-feedback d-block');
                            $("#workerCountInput").removeClass('is-valid');
                            $("#workerCountInput").addClass('is-invalid');
                        } else if (error['path'] === 'worker/group_limits/io') {
                            $('#ioLimitFeedback').text(error['error']);
                            $('#ioLimitFeedback').addClass('invalid-feedback d-block');
                            $("#ioLimitInput").removeClass('is-valid');
                            $("#ioLimitInput").addClass('is-invalid');
                        } else if (error['path'] === 'worker/group_limits/net') {
                            $('#netLimitFeedback').text(error['error']);
                            $('#netLimitFeedback').addClass('invalid-feedback d-block');
                            $("#netLimitInput").removeClass('is-valid');
                            $("#netLimitInput").addClass('is-invalid');
                        }
                    });
                }
            } else {
                $('#workerCountFeedback').text('');
                $('#workerCountFeedback').removeClass('invalid-feedback d-block');
                $("#workerCountInput").removeClass('is-invalid');
                $("#workerCountInput").addClass('is-valid');
                $('#ioLimitFeedback').text('');
                $('#ioLimitFeedback').removeClass('invalid-feedback d-block');
                $("#ioLimitInput").removeClass('is-invalid');
                $("#ioLimitInput").addClass('is-valid');
                $('#netLimitFeedback').text('');
                $('#netLimitFeedback').removeClass('invalid-feedback d-block');
                $("#netLimitInput").removeClass('is-invalid');
                $("#netLimitInput").addClass('is-valid');
            }
            $('#submitWorkerSettingsBtn').prop('disabled', false);
        }
    });
}

function importSettings() {
    const fileInput = document.getElementById('importSettingsFile');
    const feedback = $('#importSettingsFeedback');
    const btn = $('#importSettingsBtn').prop('disabled', true);
    feedback.removeClass('text-danger text-success').text('');

    if (!fileInput.files.length) {
        feedback.addClass('text-danger').text(I18N.importNoFile);
        btn.prop('disabled', false);
        return;
    }

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    fetch('/api/settings/import', {method: 'POST', body: formData, credentials: 'same-origin'})
        .then(r => r.json().then(body => ({ok: r.ok, body})))
        .then(({ok, body}) => {
            if (ok && body.success) {
                feedback.addClass('text-success').text(I18N.importSuccess);
                fileInput.value = '';
            } else {
                const template = I18N.importFailed;
                feedback.addClass('text-danger').text(template.replace('{error}', body.error || 'unknown error'));
            }
        })
        .catch(e => {
            const template = I18N.importFailed;
            feedback.addClass('text-danger').text(template.replace('{error}', e.message));
        })
        .finally(() => btn.prop('disabled', false));
}
$('#importSettingsBtn').on('click', importSettings);

// --- Reset library tracking: type-to-confirm, since this is destructive and
// irreversible - a plain confirm() dialog is too easy to click through without
// reading. -----------------------------------------------------------------

const RESET_LIBRARY_MUTATION = `
    mutation ResetLibraryTracking($confirm: String!) {
        resetLibraryTracking(confirm: $confirm)
    }`;

const resetLibraryModalEl = document.getElementById('resetLibraryModal');
const resetConfirmInput = $('#resetLibraryConfirmInput');
const resetConfirmBtn = $('#resetLibraryConfirmBtn');
const resetFeedback = $('#resetLibraryFeedback');

resetConfirmInput.on('input', function () {
    resetConfirmBtn.prop('disabled', $(this).val() !== 'RESET');
});

resetLibraryModalEl.addEventListener('hidden.bs.modal', () => {
    // Reset the form each time the modal closes, so a stray leftover "RESET"
    // from a previous open can't leave the button armed next time.
    resetConfirmInput.val('');
    resetConfirmBtn.prop('disabled', true);
    resetFeedback.removeClass('text-success text-danger').text('');
});

resetConfirmBtn.on('click', async function () {
    const btn = $(this).prop('disabled', true);
    resetFeedback.removeClass('text-success text-danger').text('');
    try {
        const r = await fetch('/api/graphql', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
            credentials: 'same-origin',
            body: JSON.stringify({
                query: RESET_LIBRARY_MUTATION,
                variables: {confirm: resetConfirmInput.val()},
            }),
        });
        if (!r.ok) throw new Error(`GraphQL HTTP ${r.status}`);
        const body = await r.json();
        if (body.errors && body.errors.length) {
            throw new Error('GraphQL errors: ' + JSON.stringify(body.errors));
        }
        const n = body.data.resetLibraryTracking;
        resetFeedback.addClass('text-success').text(I18N.resetSuccess.replace('{n}', n));
        setTimeout(() => bootstrap.Modal.getOrCreateInstance(resetLibraryModalEl).hide(), 2000);
    } catch (e) {
        console.error(e);
        resetFeedback.addClass('text-danger').text(I18N.resetFailed);
        btn.prop('disabled', false);
    }
});

$(document).ready(function () {
    fillUserTable();
    fillLibraryTable();

    // Add real-time password validation
    $('#inputNewUserPassword').on('input', function() {
        const password = $(this).val();
        const validation = validatePassword(password);
        if (!validation.isValid) {
            showPasswordError(validation.message);
        } else {
            clearPasswordError();
        }
    });

    // Add real-time username validation
    $('#inputNewUser').on('input', function() {
        const username = $(this).val();
        const validation = validateUsername(username);
        if (!validation.isValid) {
            showUsernameError(validation.message);
        } else if (allUsernames.includes(username)) {
            showUsernameError('User already exists');
        } else {
            clearUsernameError();
        }
    });

    $.getJSON("/api/settings", function (result) {
        languages = JSON.parse(document.getElementById('settingsLanguages').textContent);
        Object.keys(languages).forEach(function (key) {
            $('#selectRegion').append(`<option value="${key}">${key}</option>`);
            $('#organizerNameRegionSelect').append(`<option value="${key}">${key}</option>`);
        });

        $('#selectRegion').on('change', function () {
            $('#selectLanguage').empty()
            region = $(this).find(":selected").val();
            availableLanguages = languages[region];
            availableLanguages.forEach(function (key) {
                $('#selectLanguage').append(`<option value="${key}">${key}</option>`);
            });
        });

        // Same cascading region -> language behavior as above, except the region
        // can also be cleared back to "" ("Same as library language"), which
        // leaves the language select empty and disables the naming-language
        // override entirely.
        $('#organizerNameRegionSelect').on('change', function () {
            $('#organizerNameLanguageSelect').empty();
            const region = $(this).find(":selected").val();
            if (!region) {
                $('#organizerNameLanguageSelect').prop('disabled', true);
                return;
            }
            $('#organizerNameLanguageSelect').prop('disabled', false);
            (languages[region] || []).forEach(function (key) {
                $('#organizerNameLanguageSelect').append(`<option value="${key}">${key}</option>`);
            });
        });
        $('#organizerNameLanguageSelect').prop('disabled', true);

        // The two tie-break preferences only ever take effect once
        // library.management.duplicates.auto_resolve is itself on (see
        // tasks.py's resolve_duplicate_files_task, which no-ops entirely while
        // it's off) - greyed out otherwise so it's clear they're inert, not
        // just unchecked, and the page reads as fully manual.
        function syncDuplicateTieBreakControls() {
            const auto = $('#autoResolveDuplicatesCheck').is(':checked');
            $('#preferMulticontentCheck').prop('disabled', !auto);
            $('#preferLargerOnTieCheck').prop('disabled', !auto);
            $('#compressionPreferenceSelect').prop('disabled', !auto);
        }
        $('#autoResolveDuplicatesCheck').on('change', syncDuplicateTieBreakControls);

        // Library settings
        librarySettings = result['library'];
        // Populate library management settings
        const compression = librarySettings['management']['compression'];
        $("#compressFilesCheck").prop("checked", compression['enabled']);
        setInputVal("compressionLevelInput", compression['level']);
        $("#compressLongDistanceCheck").prop("checked", compression['long_distance']);
        setInputVal("compressModeSelect", compression['mode']);
        setInputVal("compressBlockSizeInput", compression['block_size_exponent']);
        setInputVal("compressThreadsInput", compression['threads']);
        const verification = librarySettings['management']['verification'];
        $("#verifyFilesCheck").prop("checked", verification['enabled']);
        $("input[name='verificationDepth'][value='" + verification['depth'] + "']").prop("checked", true);
        $("#deleteOlderUpdatesCheck").prop("checked", librarySettings['management']['delete_older_updates']);
        $("#webDownloadsEnabledCheck").prop("checked", (librarySettings['management']['web_downloads'] || {}).enabled || false);
        $("#autoResolveDuplicatesCheck").prop("checked", (librarySettings['management']['duplicates'] || {}).auto_resolve || false);
        $("#preferMulticontentCheck").prop("checked", (librarySettings['management']['duplicates'] || {}).prefer_multicontent || false);
        $("#preferLargerOnTieCheck").prop("checked", (librarySettings['management']['duplicates'] || {}).prefer_larger_on_tie || false);
        $("#compressionPreferenceSelect").val((librarySettings['management']['duplicates'] || {}).compression_preference || "none");
        syncDuplicateTieBreakControls();
        $("#organizerEnabledCheck").prop("checked", librarySettings['management']['organizer']['enabled']);
        $("#removeEmptyFoldersCheck").prop("checked", librarySettings['management']['organizer']['remove_empty_folders']);
        $("#windowsCompatibleCheck").prop("checked", librarySettings['management']['organizer']['windows_compatible']);
        $("#cleanNamesCheck").prop("checked", librarySettings['management']['organizer']['clean_names']);
        $("#showBackgroundImageCheck").prop("checked",
            librarySettings['management']['organizer']['show_background_image'] !== false);
        setInputVal("baseTemplateInput", librarySettings['management']['organizer']['templates']['base']);
        setInputVal("updateTemplateInput", librarySettings['management']['organizer']['templates']['update']);
        setInputVal("dlcTemplateInput", librarySettings['management']['organizer']['templates']['dlc']);
        setInputVal("multiTemplateInput", librarySettings['management']['organizer']['templates']['multi']);

        // Fill the organizer's naming-language region/language, if configured
        const organizerNameRegion = librarySettings['management']['organizer']['name_region'] || '';
        setInputVal("organizerNameRegionSelect", organizerNameRegion);
        $('#organizerNameRegionSelect').trigger('change');
        if (organizerNameRegion) {
            setInputVal("organizerNameLanguageSelect", librarySettings['management']['organizer']['name_language'] || '');
        }

        // Titles settings
        titlesSettings = result['titles'];
        updateKeysElements(titlesSettings);

        // Fill region and language
        setInputVal("selectRegion", titlesSettings['region']);
        $('#selectRegion').trigger('change');
        setInputVal("selectLanguage", titlesSettings['language']);

        // Scheduler settings
        schedulerSettings = result['scheduler'];
        if (schedulerSettings && schedulerSettings['titledb_update_interval'] !== undefined) {
            setInputVal("titledbUpdateIntervalInput", schedulerSettings['titledb_update_interval']);
        }

        fillMaintenanceSettings(result['maintenance']);
        fillNotificationSettings(result['notifications']);

        // Worker settings
        workerSettings = result['worker'];
        if (workerSettings && workerSettings['count'] !== undefined) {
            $('#workerCountInput').val(workerSettings['count']);
        }
        if (workerSettings && workerSettings['group_limits'] && workerSettings['group_limits']['io'] !== undefined) {
            $('#ioLimitInput').val(workerSettings['group_limits']['io']);
        }
        if (workerSettings && workerSettings['group_limits'] && workerSettings['group_limits']['net'] !== undefined) {
            $('#netLimitInput').val(workerSettings['group_limits']['net']);
        }

        // Local artworks
        $("#localMediaEnabledCheck").prop("checked", (result['local_media'] || {}).enabled !== false);

        // Shop settings
        shopSettings = result['shop'];
        setInputVal("shopNameInput", shopSettings['name']);
        setInputVal("shopHostInput", shopSettings['host']);
        $("#publicShopCheck").prop("checked", shopSettings['public']);
        setInputVal("shopMotdTextArea", shopSettings['motd']);

        // Check for missing shop host
        if (!shopSettings['host']) {
            $("#missingShopHostAlert").css('display', '');
        }
        
        // Client-specific settings
        if (shopSettings['clients']) {
            if (shopSettings['clients']['tinfoil']) {
                tinfoilSettings = shopSettings['clients']['tinfoil'];
                $("#tinfoilEnabledCheck").prop("checked", tinfoilSettings['enabled']);
                $("#tinfoilEncryptShopCheck").prop("checked", tinfoilSettings['encrypt']);
            }
            if (shopSettings['clients']['sphaira']) {
                sphairaSettings = shopSettings['clients']['sphaira'];
                $("#sphairaEnabledCheck").prop("checked", sphairaSettings['enabled']);
            }
            if (shopSettings['clients']['cyberfoil']) {
                cyberfoilSettings = shopSettings['clients']['cyberfoil'];
                $("#cyberfoilEnabledCheck").prop("checked", cyberfoilSettings['enabled']);
            }
        }
    });

});
// Without an admin yet, the first user created has to be one.
if (!ADMIN_ACCOUNT_CREATED) {
    $('#checkboxNewUserAdminAccess').prop('checked', true).attr("disabled", true);
    $('#checkboxNewUserShopAccess').prop('checked', true).attr("disabled", true);
    $('#checkboxNewUserBackupAccess').prop('checked', true).attr("disabled", true);
}
